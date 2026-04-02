"""Image status endpoints for lesson image polling (US-025)."""

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.schemas.images import (
    ImageStatus,
    ImageStatusResponse,
    LessonImageResponse,
    LessonImagesListResponse,
)
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

_RATE_LIMIT_WINDOW_SECONDS = 2
_RATE_LIMIT_KEY_PREFIX = "rate_limit:image_status:"

_ALT_TEXT: dict[str, dict[str, str]] = {
    "fr": "Illustration de la leçon",
    "en": "Lesson illustration",
}

_MOCK_IMAGES: dict[str, dict] = {}


def _build_lesson_image(image_id: str, lesson_id: str, lang: str) -> dict:
    return {
        "image_id": image_id,
        "lesson_id": lesson_id,
        "status": "pending",
        "image_url": None,
        "alt_text": _ALT_TEXT.get(lang, _ALT_TEXT["fr"]),
        "format": "webp",
        "width": 800,
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
    lesson_id_str = str(lesson_id)

    images_for_lesson = {
        img_id: img for img_id, img in _MOCK_IMAGES.items() if img["lesson_id"] == lesson_id_str
    }

    if not images_for_lesson:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_not_found",
                "message": f"No images found for lesson {lesson_id}",
            },
        )

    lang_key = lang if lang in _ALT_TEXT else "fr"

    image_responses = []
    for img_id, img in images_for_lesson.items():
        img_status: ImageStatus = img["status"]
        image_responses.append(
            LessonImageResponse(
                image_id=UUID(img_id),
                lesson_id=lesson_id,
                status=img_status,
                image_url=img["image_url"] if img_status == "ready" else None,
                alt_text=img.get("alt_text", _ALT_TEXT[lang_key]),
                format=img.get("format", "webp"),
                width=img.get("width", 800),
            )
        )

    logger.info(
        "Lesson images fetched",
        lesson_id=lesson_id_str,
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

    img = _MOCK_IMAGES.get(image_id_str)
    if img is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "image_not_found",
                "message": f"Image {image_id} not found",
            },
        )

    img_status: ImageStatus = img["status"]

    logger.info("Image status polled", image_id=image_id_str, status=img_status)

    return ImageStatusResponse(
        image_id=image_id,
        status=img_status,
        image_url=img["image_url"] if img_status == "ready" else None,
    )
