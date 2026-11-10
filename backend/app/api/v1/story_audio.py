"""Story read-aloud with OpenAI TTS (#2704).

* ``POST /api/v1/story-audio`` (signed in): the clip of one line in one voice,
  synthesized on first request and cached for every learner after that.
* ``GET /api/v1/story-audio/{id}/data`` (no token, so a plain ``<audio src>``
  works, like ``/story-art/{id}/data``): the OGG Opus clip, cached as immutable.
  A clip's id always names the same audio.

New syntheses are capped per learner per day
(``settings.story_tts_daily_new_lines_per_user``); lines already cached are
always served. Past the cap, or when TTS fails, the player reads the line
with the browser's own voice instead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.story_audio import StoryLineAudioRequest, StoryLineAudioResponse
from app.domain.models.story_audio import StoryLineAudio
from app.domain.services.story_audio_service import (
    StoryAudioError,
    StoryAudioService,
    normalize_line,
)
from app.infrastructure.cache.redis import redis_client
from app.infrastructure.config.settings import get_settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/story-audio", tags=["Story audio"])

IMMUTABLE = "public, max-age=31536000, immutable"


def _clip_url(clip_id: uuid.UUID) -> str:
    return f"/api/v1/story-audio/{clip_id}/data"


async def _take_new_line_quota(user_id: str, cap: int) -> bool:
    """Count one new synthesis against today's cap. True if it is allowed.

    Redis being down never blocks read-aloud: the cap is a cost guard, not a
    security boundary.
    """
    key = f"story_tts:new_lines:{user_id}:{datetime.now(UTC):%Y%m%d}"
    try:
        used = await redis_client.incr(key)
        if used == 1:
            await redis_client.expire(key, 2 * 24 * 3600)
        return used <= cap
    except Exception:
        return True


@router.post("", response_model=StoryLineAudioResponse)
async def story_line_audio(
    body: StoryLineAudioRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> StoryLineAudioResponse:
    """The clip of one story line, synthesized on first request."""
    text = normalize_line(body.text)
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "empty_line", "message": "Nothing to read"},
        )

    cached = await StoryAudioService.find_cached(text, body.language, body.voice, db)
    if cached is not None:
        return StoryLineAudioResponse(id=cached.id, url=_clip_url(cached.id))

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "tts_not_configured", "message": "TTS is not configured"},
        )
    if not await _take_new_line_quota(
        str(current_user.id), settings.story_tts_daily_new_lines_per_user
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"error": "story_tts_daily_cap", "message": "Daily read-aloud limit reached"},
        )

    try:
        user_uuid = uuid.UUID(str(current_user.id))
    except ValueError:
        user_uuid = None
    try:
        clip = await StoryAudioService().synthesize(
            text, body.language, body.voice, db, user_id=user_uuid
        )
    except StoryAudioError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "story_tts_failed", "message": "Audio synthesis failed"},
        ) from exc
    return StoryLineAudioResponse(id=clip.id, url=_clip_url(clip.id))


@router.get(
    "/{clip_id}/data",
    responses={
        200: {"content": {"audio/ogg": {}}, "description": "The clip (OGG Opus)"},
        404: {"description": "Unknown clip, or its audio is gone"},
    },
)
async def story_line_audio_data(
    clip_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """One story line's clip, cached as immutable."""
    storage_key = (
        await db.execute(select(StoryLineAudio.storage_key).where(StoryLineAudio.id == clip_id))
    ).scalar_one_or_none()
    if storage_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_audio_not_found", "message": f"No story audio {clip_id}"},
        )
    try:
        audio_bytes = await S3StorageService().download_bytes(storage_key)
    except Exception as exc:
        logger.warning(
            "Story audio download failed",
            clip_id=str(clip_id),
            storage_key=storage_key,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_audio_unavailable", "message": "Audio data unavailable"},
        ) from exc
    return Response(
        content=audio_bytes, media_type="audio/ogg", headers={"Cache-Control": IMMUTABLE}
    )
