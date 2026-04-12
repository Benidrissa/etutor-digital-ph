"""Lesson audio status endpoints for polling (mirrors images.py pattern)."""

import time
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.v1.schemas.audio import (
    AudioStatus,
    AudioStatusResponse,
    LessonAudioListResponse,
    LessonAudioResponse,
)
from app.domain.models.generated_audio import GeneratedAudio
from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/audio", tags=["audio"])

_RATE_LIMIT_WINDOW_SECONDS = 2
_RATE_LIMIT_KEY_PREFIX = "rate_limit:audio_status:"


async def _check_rate_limit(audio_id: str) -> bool:
    """Return True if request is allowed, False if rate-limited (1 req per 2s)."""
    key = f"{_RATE_LIMIT_KEY_PREFIX}{audio_id}"
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


def _resolve_audio_url(audio: GeneratedAudio) -> str | None:
    if audio.status != "ready":
        return None
    return f"/api/v1/audio/{audio.id}/data"


@router.get(
    "/lesson/{lesson_id}",
    response_model=LessonAudioListResponse,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Lesson audio not found"}},
)
async def get_lesson_audio(
    lesson_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> LessonAudioListResponse:
    """Return audio for a lesson by (module_id, unit_id, language) — shared across countries."""
    from app.domain.models.content import GeneratedContent

    # Look up lesson metadata to get module_id, unit_id, language
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
            detail={"error": "lesson_not_found", "message": f"Lesson {lesson_id} not found"},
        )

    # Query audio by (module_id, unit_id, language) — shared across all countries
    result = await db.execute(
        select(GeneratedAudio).where(
            GeneratedAudio.module_id == lesson_meta.module_id,
            GeneratedAudio.unit_id == lesson_meta.unit_id,
            GeneratedAudio.language == lesson_meta.language,
        )
    )
    db_audio = result.scalars().all()

    if not db_audio:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "lesson_audio_not_found",
                "message": f"No audio for lesson {lesson_id}",
            },
        )

    return _build_response(lesson_id, db_audio)


def _build_response(
    lesson_id: UUID,
    db_audio: list[GeneratedAudio],
) -> LessonAudioListResponse:
    audio_responses = []
    for aud in db_audio:
        aud_status: AudioStatus = aud.status
        audio_responses.append(
            LessonAudioResponse(
                audio_id=aud.id,
                lesson_id=lesson_id,
                status=aud_status,
                audio_url=_resolve_audio_url(aud),
                duration_seconds=aud.duration_seconds if aud.status == "ready" else None,
                file_size_bytes=aud.file_size_bytes if aud.status == "ready" else None,
            )
        )

    logger.info(
        "Lesson audio fetched",
        lesson_id=str(lesson_id),
        count=len(audio_responses),
    )

    return LessonAudioListResponse(
        lesson_id=lesson_id,
        audio=audio_responses,
        total=len(audio_responses),
    )


@router.get(
    "/{audio_id}/status",
    response_model=AudioStatusResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"description": "Audio not found"},
        429: {"description": "Rate limit exceeded — max 1 req/2s per audio"},
    },
)
async def get_audio_status(
    audio_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> AudioStatusResponse:
    """Lightweight polling endpoint for audio generation status."""
    audio_id_str = str(audio_id)

    allowed = await _check_rate_limit(audio_id_str)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": "Too many requests — poll at most once every 2 seconds",
                "retry_after": _RATE_LIMIT_WINDOW_SECONDS,
            },
            headers={"Retry-After": str(_RATE_LIMIT_WINDOW_SECONDS)},
        )

    result = await db.execute(select(GeneratedAudio).where(GeneratedAudio.id == audio_id))
    aud = result.scalar_one_or_none()

    if aud is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "audio_not_found",
                "message": f"Audio {audio_id} not found",
            },
        )

    aud_status: AudioStatus = aud.status

    logger.info("Audio status polled", audio_id=audio_id_str, status=aud_status)

    return AudioStatusResponse(
        audio_id=audio_id,
        status=aud_status,
        audio_url=_resolve_audio_url(aud),
        duration_seconds=aud.duration_seconds if aud.status == "ready" else None,
    )


@router.get(
    "/{audio_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"audio/ogg": {}}, "description": "OGG Opus audio data"},
        404: {"description": "Audio not found or not ready"},
    },
)
async def get_audio_data(
    audio_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Serve the MP3 audio file for a lesson summary."""
    result = await db.execute(select(GeneratedAudio).where(GeneratedAudio.id == audio_id))
    aud = result.scalar_one_or_none()

    if aud is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "audio_not_found",
                "message": f"Audio {audio_id} not found",
            },
        )

    if aud.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "audio_not_ready",
                "message": f"Audio {audio_id} is not ready (status: {aud.status})",
            },
        )

    # Proxy audio bytes from MinIO (internal URL not accessible from browser)
    if aud.storage_key:
        try:
            from app.infrastructure.storage.s3 import S3StorageService

            storage = S3StorageService()
            audio_bytes = await storage.download_bytes(aud.storage_key)
            return Response(
                content=audio_bytes,
                media_type="audio/ogg",
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        except Exception as exc:
            logger.warning("S3 download failed", key=aud.storage_key, error=str(exc))

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "audio_data_unavailable",
            "message": f"Audio {audio_id} has no stored data",
        },
    )
