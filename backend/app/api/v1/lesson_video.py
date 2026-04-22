"""Lesson video summary endpoints.

Per-lesson video generation scoped by ``(module_id, unit_id,
language)``, mirroring the ``lesson_audio`` surface but for HeyGen
MP4 output. Trigger is explicit — admin or learner posts to
``/api/v1/video/lesson/{lesson_id}/generate`` — so tenants don't
eat HeyGen's per-minute cost on every auto-generated lesson.

Shares the ``generated_audio`` table with ``media_type='video'``
(see #1802).
"""

from __future__ import annotations

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.video import (
    GenerateLessonVideoResponse,
    LessonVideoListResponse,
    LessonVideoResponse,
    VideoStatus,
    VideoStatusResponse,
)
from app.domain.models.generated_audio import GeneratedAudio
from app.domain.services.platform_settings_service import SettingsCache
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/video", tags=["video"])

_RATE_LIMIT_WINDOW_SECONDS = 2
_RATE_LIMIT_KEY_PREFIX = "rate_limit:video_status:"


async def _check_rate_limit(video_id: str) -> bool:
    """Allow 1 status poll per 2s per row — same contract as audio."""
    key = f"{_RATE_LIMIT_KEY_PREFIX}{video_id}"
    try:
        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW_SECONDS
        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, "-inf", window_start)
        pipe.zadd(key, {str(now): now})
        pipe.zcard(key)
        pipe.expire(key, _RATE_LIMIT_WINDOW_SECONDS + 1)
        results = await pipe.execute()
        return results[2] <= 1
    except Exception:
        return True


def _resolve_video_url(row: GeneratedAudio) -> str | None:
    if row.status != "ready":
        return None
    return f"/api/v1/video/{row.id}/data"


@router.post(
    "/lesson/{lesson_id}/generate",
    response_model=GenerateLessonVideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        403: {"description": "video_summary feature disabled"},
        404: {"description": "Lesson not found"},
    },
)
async def generate_lesson_video(
    lesson_id: UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> GenerateLessonVideoResponse:
    """Kick off (or return in-flight) a HeyGen video summary for a lesson.

    Any authenticated user can trigger — learners may want a video
    for their own consumption, admins may pre-seed popular lessons.
    The underlying Celery task is feature-flag gated, so disabling
    the feature turns the button into a no-op without removing it
    from the UI.
    """
    if not bool(SettingsCache.instance().get("video-summary-feature-enabled", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "video_summary_disabled",
                "message": "Video summaries are disabled for this tenant",
            },
        )

    # Resolve lesson → (module_id, unit_id, language) so we can
    # return an existing row if a prior call already dispatched.
    from app.domain.models.content import GeneratedContent

    lesson_row = await db.execute(
        select(
            GeneratedContent.module_id,
            GeneratedContent.language,
            GeneratedContent.content["unit_id"].as_string().label("unit_id"),
            GeneratedContent.content.label("content"),
        ).where(GeneratedContent.id == lesson_id)
    )
    lesson_meta = lesson_row.first()
    if not lesson_meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_not_found",
                "message": f"Lesson {lesson_id} not found",
            },
        )

    # Cache hit / in-flight: return the existing row instead of
    # spawning a second generation.
    existing = await db.execute(
        select(GeneratedAudio)
        .where(
            GeneratedAudio.module_id == lesson_meta.module_id,
            GeneratedAudio.unit_id == lesson_meta.unit_id,
            GeneratedAudio.media_type == "video",
            GeneratedAudio.language == lesson_meta.language,
        )
        .order_by(GeneratedAudio.created_at.desc())
        .limit(1)
    )
    row = existing.scalar_one_or_none()
    if row is not None and row.status in ("ready", "generating", "pending"):
        return GenerateLessonVideoResponse(
            video_id=row.id,
            status=row.status,  # type: ignore[arg-type]
            message=(
                "Video already available"
                if row.status == "ready"
                else "Generation already in progress"
            ),
        )

    # Fresh dispatch. Extract lesson text from the cached content
    # JSON — same shape the audio service uses.
    content = lesson_meta.content or {}
    lesson_text_fragments: list[str] = []
    for key in ("introduction", "aof_example", "synthesis"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            lesson_text_fragments.append(value)
    concepts = content.get("concepts") or []
    if isinstance(concepts, list):
        for c in concepts:
            if isinstance(c, str) and c.strip():
                lesson_text_fragments.append(c)
    lesson_content_text = "\n\n".join(lesson_text_fragments) or (content.get("title") or "")

    from app.tasks.content_generation import generate_lesson_video as task

    task.delay(
        str(lesson_id),
        str(lesson_meta.module_id),
        lesson_meta.unit_id,
        lesson_meta.language,
        lesson_content_text,
    )

    logger.info(
        "Lesson video generation dispatched",
        lesson_id=str(lesson_id),
        module_id=str(lesson_meta.module_id),
        unit_id=lesson_meta.unit_id,
        language=lesson_meta.language,
    )

    # Return a synthetic pending response; the task will insert the
    # actual row (or find an existing one) when it runs.
    return GenerateLessonVideoResponse(
        video_id=row.id if row is not None else lesson_id,
        status="pending",
        message="Video generation started — usually ready in 10–15 minutes",
    )


@router.get(
    "/lesson/{lesson_id}",
    response_model=LessonVideoListResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "No video for this lesson"}},
)
async def get_lesson_video(
    lesson_id: UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> LessonVideoListResponse:
    """Return video rows for a lesson, shared across countries."""
    from app.domain.models.content import GeneratedContent

    lesson_row = await db.execute(
        select(
            GeneratedContent.module_id,
            GeneratedContent.language,
            GeneratedContent.content["unit_id"].as_string().label("unit_id"),
        ).where(GeneratedContent.id == lesson_id)
    )
    lesson_meta = lesson_row.first()
    if not lesson_meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_not_found",
                "message": f"Lesson {lesson_id} not found",
            },
        )

    result = await db.execute(
        select(GeneratedAudio).where(
            GeneratedAudio.module_id == lesson_meta.module_id,
            GeneratedAudio.unit_id == lesson_meta.unit_id,
            GeneratedAudio.media_type == "video",
            GeneratedAudio.language == lesson_meta.language,
        )
    )
    rows = result.scalars().all()

    video_responses = []
    for row in rows:
        row_status: VideoStatus = row.status  # type: ignore[assignment]
        video_responses.append(
            LessonVideoResponse(
                video_id=row.id,
                lesson_id=lesson_id,
                status=row_status,
                video_url=_resolve_video_url(row),
                duration_seconds=row.duration_seconds if row.status == "ready" else None,
                file_size_bytes=row.file_size_bytes if row.status == "ready" else None,
            )
        )

    if not video_responses:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_video_not_found",
                "message": f"No video for lesson {lesson_id}",
            },
        )

    return LessonVideoListResponse(
        lesson_id=lesson_id,
        video=video_responses,
        total=len(video_responses),
    )


@router.get(
    "/{video_id}/status",
    response_model=VideoStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Video row not found"},
        429: {"description": "Rate limit exceeded — max 1 req/2s per video"},
    },
)
async def get_video_status(
    video_id: UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VideoStatusResponse:
    """Lightweight polling endpoint for video generation status."""
    vid_str = str(video_id)
    if not await _check_rate_limit(vid_str):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Too many requests — poll at most once every 2 seconds",
                "retry_after": _RATE_LIMIT_WINDOW_SECONDS,
            },
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
        )

    result = await db.execute(
        select(GeneratedAudio).where(
            GeneratedAudio.id == video_id,
            GeneratedAudio.media_type == "video",
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_not_found",
                "message": f"Video {video_id} not found",
            },
        )

    row_status: VideoStatus = row.status  # type: ignore[assignment]
    return VideoStatusResponse(
        video_id=video_id,
        status=row_status,
        video_url=_resolve_video_url(row),
        duration_seconds=row.duration_seconds if row.status == "ready" else None,
    )


@router.get(
    "/{video_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"video/mp4": {}}, "description": "MP4 video data"},
        404: {"description": "Video not found or not ready"},
    },
)
async def get_video_data(
    video_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Proxy the MP4 bytes from MinIO (internal URL not browser-reachable).

    Public (no ``get_current_user``) because native ``<video src=...>``
    elements do not send ``Authorization`` headers. Mirrors the audio
    ``/{audio_id}/data`` contract. Access control is upstream: the
    lesson-video rows themselves are only written by authenticated
    dispatches, and the ``status='ready'`` + ``media_type='video'``
    gates prevent serving in-progress or non-video rows.
    """
    result = await db.execute(
        select(GeneratedAudio).where(
            GeneratedAudio.id == video_id,
            GeneratedAudio.media_type == "video",
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_not_found",
                "message": f"Video {video_id} not found",
            },
        )
    if row.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_not_ready",
                "message": f"Video {video_id} is not ready (status: {row.status})",
            },
        )
    if not row.storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_data_unavailable",
                "message": f"Video {video_id} has no stored data",
            },
        )

    try:
        from app.infrastructure.storage.s3 import S3StorageService

        storage = S3StorageService()
        video_bytes = await storage.download_bytes(row.storage_key)
        return Response(
            content=video_bytes,
            media_type="video/mp4",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    except Exception as exc:
        logger.warning(
            "S3 download failed",
            key=row.storage_key,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "video_data_unavailable",
                "message": f"Video {video_id} download failed",
            },
        ) from exc
