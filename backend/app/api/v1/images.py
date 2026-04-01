"""Image status endpoints for lesson image polling (US-025)."""

import time
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.v1.schemas.images import (
    ImageStatusResponse,
    LessonImageResponse,
    LessonImagesListResponse,
)
from app.domain.models.content import GeneratedContent
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/images", tags=["images"])

_POLL_RATE_LIMIT_WINDOW = 2
_POLL_RATE_LIMIT_MAX = 1


async def _check_poll_rate_limit(image_id: str, client_ip: str) -> None:
    """Enforce max 1 request per 2 seconds per image per IP."""
    cache_key = f"rate_limit:image_poll:{image_id}:{client_ip}"
    current_time = int(time.time())
    window_start = current_time - _POLL_RATE_LIMIT_WINDOW

    try:
        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(cache_key, 0, window_start)
        pipe.zcard(cache_key)
        pipe.zadd(cache_key, {str(current_time): current_time})
        pipe.expire(cache_key, _POLL_RATE_LIMIT_WINDOW + 1)
        results = await pipe.execute()
        request_count = results[1]

        if request_count >= _POLL_RATE_LIMIT_MAX:
            logger.warning(
                "Image poll rate limit exceeded",
                image_id=image_id,
                client_ip=client_ip,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "Maximum 1 request per 2 seconds per image",
                    "retry_after": _POLL_RATE_LIMIT_WINDOW,
                },
                headers={"Retry-After": str(_POLL_RATE_LIMIT_WINDOW)},
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Image poll rate limit check failed",
            image_id=image_id,
            exception=str(exc),
        )


def _build_lesson_image_response(
    record: GeneratedContent,
    lang: str,
) -> LessonImageResponse:
    """Build a LessonImageResponse from a GeneratedContent row of type 'image'."""
    content = record.content or {}
    img_status = content.get("status", "pending")
    image_url = content.get("image_url") if img_status == "ready" else None
    alt_text_key = f"alt_text_{lang}" if f"alt_text_{lang}" in content else "alt_text"
    alt_text = content.get(alt_text_key) or content.get("alt_text")

    return LessonImageResponse(
        id=record.id,
        lesson_id=uuid.UUID(str(content.get("lesson_id", record.module_id))),
        status=img_status,
        image_url=image_url,
        alt_text=alt_text,
        format=content.get("format"),
        width=content.get("width"),
    )


@router.get(
    "/lesson/{lesson_id}",
    response_model=LessonImagesListResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Lesson not found"},
        500: {"description": "Internal server error"},
    },
    summary="List images for a lesson",
)
async def get_lesson_images(
    lesson_id: uuid.UUID,
    lang: str = "fr",
    session: AsyncSession = Depends(get_db),
    response: Response = None,
) -> LessonImagesListResponse:
    """
    Return all images associated with a lesson.

    **Status values:**
    - `pending` — queued, image_url is null
    - `generating` — in progress, image_url is null
    - `ready` — image_url is present, long-lived cache headers are set
    - `failed` — generation failed, image_url is null

    **Cache headers:**
    - Ready images: `Cache-Control: public, max-age=31536000, immutable`
    - Non-ready images: `Cache-Control: no-store`

    Use `?lang=fr` or `?lang=en` to receive localized alt_text.
    """
    try:
        query = select(GeneratedContent).where(
            GeneratedContent.content_type == "image",
        )
        result = await session.execute(query)
        all_images = result.scalars().all()

        lesson_id_str = str(lesson_id)
        images = [
            row for row in all_images if str(row.content.get("lesson_id", "")) == lesson_id_str
        ]

        if not images:
            lesson_query = select(GeneratedContent).where(
                GeneratedContent.id == lesson_id,
                GeneratedContent.content_type == "lesson",
            )
            lesson_result = await session.execute(lesson_query)
            lesson = lesson_result.scalar_one_or_none()
            if lesson is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "lesson_not_found",
                        "message": f"Lesson {lesson_id} not found",
                    },
                )
            if response is not None:
                response.headers["Cache-Control"] = "no-store"
            return LessonImagesListResponse(lesson_id=lesson_id, images=[])

        image_responses = [_build_lesson_image_response(row, lang) for row in images]

        all_ready = all(img.status == "ready" for img in image_responses)
        if response is not None:
            if all_ready:
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-store"

        logger.info(
            "Lesson images retrieved",
            lesson_id=lesson_id_str,
            image_count=len(image_responses),
            lang=lang,
        )

        return LessonImagesListResponse(lesson_id=lesson_id, images=image_responses)

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to retrieve lesson images",
            lesson_id=str(lesson_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "retrieval_failed",
                "message": "Failed to retrieve images for lesson",
            },
        )


@router.get(
    "/{image_id}/status",
    response_model=ImageStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Image not found"},
        429: {"description": "Rate limit exceeded (max 1 req/2s per image)"},
        500: {"description": "Internal server error"},
    },
    summary="Poll image generation status",
)
async def get_image_status(
    image_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_db),
    response: Response = None,
) -> ImageStatusResponse:
    """
    Lightweight endpoint for polling a single image's generation status.

    **Rate limit:** maximum 1 request per 2 seconds per image (returns 429 otherwise).

    **Cache headers:**
    - `ready` images: `Cache-Control: public, max-age=31536000, immutable`
    - All other statuses: `Cache-Control: no-store`

    The frontend should replace the image placeholder once status transitions to `ready`.
    """
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )

    await _check_poll_rate_limit(str(image_id), client_ip)

    try:
        query = select(GeneratedContent).where(
            GeneratedContent.id == image_id,
            GeneratedContent.content_type == "image",
        )
        result = await session.execute(query)
        image_record = result.scalar_one_or_none()

        if image_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "image_not_found",
                    "message": f"Image {image_id} not found",
                },
            )

        content = image_record.content or {}
        img_status = content.get("status", "pending")
        image_url = content.get("image_url") if img_status == "ready" else None

        if response is not None:
            if img_status == "ready":
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                response.headers["Cache-Control"] = "no-store"

        logger.info(
            "Image status polled",
            image_id=str(image_id),
            status=img_status,
        )

        return ImageStatusResponse(
            id=image_record.id,
            status=img_status,
            image_url=image_url,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to retrieve image status",
            image_id=str(image_id),
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "retrieval_failed",
                "message": "Failed to retrieve image status",
            },
        )
