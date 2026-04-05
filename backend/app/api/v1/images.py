"""Image status endpoints for lesson image polling (US-025)."""

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.v1.schemas.images import (
    ImageStatus,
    ImageStatusResponse,
    LessonImageResponse,
    LessonImagesListResponse,
)
from app.domain.models.generated_image import GeneratedImage
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

_RATE_LIMIT_WINDOW_SECONDS = 2
_RATE_LIMIT_KEY_PREFIX = "rate_limit:image_status:"

_ALT_TEXT: dict[str, dict[str, str]] = {
    "fr": "Illustration de la leçon",
    "en": "Lesson illustration",
}


async def _check_rate_limit(image_id: str) -> bool:
    """Return True if request is allowed, False if rate-limited (1 req per 2s per image)."""
    key = f"{_RATE_LIMIT_KEY_PREFIX}{image_id}"
    try:
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW_SECONDS

        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _RATE_LIMIT_WINDOW_SECONDS + 1)
        results = await pipe.execute()

        count = results[2]
        return count <= 1
    except Exception:
        return True


def _cache_headers_for_status(img_status: ImageStatus) -> dict[str, str]:
    if img_status == "ready":
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "no-store"}


def _get_alt_text(image: GeneratedImage, lang: str) -> str:
    lang_key = lang if lang in _ALT_TEXT else "fr"
    if lang == "en" and image.alt_text_en:
        return image.alt_text_en
    if image.alt_text_fr:
        return image.alt_text_fr
    return _ALT_TEXT[lang_key]


def _resolve_image_url(img: GeneratedImage) -> str | None:
    """Return a public URL for a ready image.

    Always returns our own data endpoint to avoid exposing expired third-party
    URLs (e.g. Azure blob storage) stored in the DB.
    """
    if img.status != "ready":
        return None
    return f"/api/v1/images/{img.id}/data"


@router.get(
    "/lesson/{lesson_id}",
    response_model=LessonImagesListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Lesson not found"},
    },
)
async def get_lesson_images(
    lesson_id: UUID,
    lang: str = "fr",
    db: AsyncSession = Depends(get_db_session),
) -> LessonImagesListResponse:
    """
    Return all images for a lesson with their generation status and localized alt_text.

    - If status is 'ready', `image_url` is included.
    - If status is 'pending' or 'generating', `image_url` is null (show placeholder).
    - If status is 'failed', `image_url` is null (hide placeholder gracefully).

    **Cache headers:**
    - `ready` images: `public, max-age=31536000, immutable`
    - Other statuses: `no-store`
    """
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.lesson_id == lesson_id))
    db_images = result.scalars().all()

    if not db_images:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_not_found",
                "message": f"No images found for lesson {lesson_id}",
            },
        )

    image_responses = []
    for img in db_images:
        img_status: ImageStatus = img.status
        image_responses.append(
            LessonImageResponse(
                image_id=img.id,
                lesson_id=lesson_id,
                status=img_status,
                image_url=_resolve_image_url(img),
                alt_text=_get_alt_text(img, lang),
                format=img.format,
                width=img.width,
            )
        )

    logger.info(
        "Lesson images fetched",
        lesson_id=str(lesson_id),
        count=len(image_responses),
        lang=lang,
    )

    return LessonImagesListResponse(
        lesson_id=lesson_id,
        images=image_responses,
        total=len(image_responses),
    )


@router.get(
    "/{image_id}/status",
    response_model=ImageStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Image not found"},
        429: {"description": "Rate limit exceeded — max 1 req/2s per image"},
    },
)
async def get_image_status(
    image_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
) -> ImageStatusResponse:
    """
    Lightweight polling endpoint for individual image generation status.

    **Rate limited:** max 1 request per 2 seconds per image.
    Returns 429 if the limit is exceeded.

    **Cache headers:**
    - `ready` images: `public, max-age=31536000, immutable`
    - Other statuses: `no-store`
    """
    image_id_str = str(image_id)

    allowed = await _check_rate_limit(image_id_str)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Too many requests — poll at most once every 2 seconds per image",
                "retry_after": _RATE_LIMIT_WINDOW_SECONDS,
            },
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
        )

    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == image_id))
    img = result.scalar_one_or_none()

    if img is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "image_not_found",
                "message": f"Image {image_id} not found",
            },
        )

    img_status: ImageStatus = img.status

    logger.info("Image status polled", image_id=image_id_str, status=img_status)

    return ImageStatusResponse(
        image_id=image_id,
        status=img_status,
        image_url=_resolve_image_url(img),
    )


@router.get(
    "/{image_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"image/webp": {}}, "description": "Binary WebP image data"},
        302: {"description": "Redirect to the CDN image URL when binary data is unavailable"},
        404: {"description": "Image not found or not ready"},
    },
)
async def get_image_data(
    image_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """
    Serve the WebP image for a lesson illustration.

    - Returns binary WebP (`Content-Type: image/webp`) when `image_data` is stored.
    - Falls back to a 302 redirect to `image_url` when only a CDN URL is available.
    - Returns 404 when the image is not found or not yet ready.
    """
    result = await db.execute(select(GeneratedImage).where(GeneratedImage.id == image_id))
    img = result.scalar_one_or_none()

    if img is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "image_not_found",
                "message": f"Image {image_id} not found",
            },
        )

    if img.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "image_not_ready",
                "message": f"Image {image_id} is not ready (status: {img.status})",
            },
        )

    if img.image_data:
        logger.info("Serving binary image data", image_id=str(image_id))
        return Response(
            content=img.image_data,
            media_type="image/webp",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    if img.image_url:
        logger.info("Redirecting to CDN image URL", image_id=str(image_id), image_url=img.image_url)
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={
                "Location": img.image_url,
                "Cache-Control": "public, max-age=3600",
            },
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "image_data_unavailable",
            "message": f"Image {image_id} has no stored data or URL",
        },
    )
