"""API endpoints for tutor voice output (#1932).

Two responsibilities:

* Per-message "listen" button — POST ``/conversations/{id}/messages/{index}/audio``
  generates (or returns cached) TTS audio for an assistant reply.
* Voice-call session — POST ``/voice-session`` mints an OpenAI Realtime
  ephemeral client token the browser uses for WebRTC voice chat, and
  ``/voice-session/close`` reconciles reported duration against the daily
  minute cap.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.tutor_voice import (
    TutorMessageAudioResponse,
    VoiceSessionCloseRequest,
    VoiceSessionCloseResponse,
    VoiceSessionRequest,
    VoiceSessionResponse,
)
from app.domain.models.conversation import TutorConversation
from app.domain.models.tutor_voice import TutorMessageAudio, TutorVoiceSession
from app.domain.services.tutor_audio_service import TutorAudioService
from app.infrastructure.config.settings import get_settings
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/tutor", tags=["tutor-voice"])

_OPENAI_REALTIME_SESSIONS_URL = "https://api.openai.com/v1/realtime/sessions"


async def _require_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    session: AsyncSession,
) -> TutorConversation:
    result = await session.execute(
        select(TutorConversation).where(
            TutorConversation.id == conversation_id,
            TutorConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conversation


@router.post(
    "/conversations/{conversation_id}/messages/{message_index}/audio",
    response_model=TutorMessageAudioResponse,
)
async def synthesize_message_audio(
    conversation_id: uuid.UUID,
    message_index: int,
    locale: str = "en",
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> TutorMessageAudioResponse:
    """Return cached TTS audio for an assistant reply, synthesizing on first call."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS is not configured.",
        )

    language = "fr" if locale == "fr" else "en"
    conversation = await _require_conversation(conversation_id, current_user.id, db)

    service = TutorAudioService()
    try:
        record = await service.synthesize_for_message(
            conversation=conversation,
            message_index=message_index,
            language=language,
            session=db,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.warning(
            "Tutor TTS synthesis failed",
            error=str(exc),
            conversation_id=str(conversation_id),
            message_index=message_index,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Audio synthesis failed. Please try again.",
        ) from exc

    # Return a relative proxy URL, not the raw MinIO storage_url — the
    # latter points to the internal container hostname (http://minio:9000)
    # which is not browser-reachable (#1949, same pattern as #1607/#1608
    # and lesson_audio.py:_resolve_audio_url).
    proxy_url = f"/api/v1/tutor/messages/{record.id}/data" if record.status == "ready" else None
    return TutorMessageAudioResponse(
        status=record.status,
        url=proxy_url,
        duration_seconds=record.duration_seconds,
        error_message=record.error_message,
    )


@router.get(
    "/messages/{audio_id}/data",
    responses={
        200: {"content": {"audio/ogg": {}}, "description": "OGG Opus audio data"},
        404: {"description": "Audio not found, not ready, or not owned by user"},
    },
)
async def get_message_audio_data(
    audio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Stream a tutor message's TTS audio from MinIO.

    Unauthenticated — matches lesson_audio's GET /audio/{id}/data pattern.
    The UUID is a 128-bit random identifier only handed to the authenticated
    user who owns the conversation, so leakage requires either their session
    token or a server compromise. Adding auth here would break the browser
    ``<audio>`` element which cannot send Bearer headers.
    """
    result = await db.execute(select(TutorMessageAudio).where(TutorMessageAudio.id == audio_id))
    audio = result.scalar_one_or_none()
    if audio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio not found",
        )
    if audio.status != "ready" or not audio.storage_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio not ready",
        )

    try:
        audio_bytes = await S3StorageService().download_bytes(audio.storage_key)
    except Exception as exc:
        logger.warning(
            "Tutor audio download failed",
            audio_id=str(audio_id),
            storage_key=audio.storage_key,
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio data unavailable",
        ) from exc

    return Response(
        content=audio_bytes,
        media_type="audio/ogg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


async def _minutes_used_today(user_id: uuid.UUID, db: AsyncSession) -> int:
    """Sum voice-session seconds for ``user_id`` since UTC midnight, rounded up to minutes."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(TutorVoiceSession.duration_seconds), 0)).where(
            TutorVoiceSession.user_id == user_id,
            TutorVoiceSession.started_at >= today_start,
        )
    )
    seconds = result.scalar() or 0
    return (int(seconds) + 59) // 60


@router.post("/voice-session", response_model=VoiceSessionResponse)
async def create_voice_session(
    body: VoiceSessionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoiceSessionResponse:
    """Mint an ephemeral OpenAI Realtime token, gated by the daily minute cap.

    403 when cap is reached, 503 when OpenAI is not configured, 402 reserved for
    the future credit-balance gate (not applied in v1).
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice calls are not configured.",
        )

    used = await _minutes_used_today(current_user.id, db)
    cap = settings.tutor_voice_daily_minutes_cap
    if used >= cap:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Daily voice-call cap reached ({cap} min). Try again tomorrow.",
        )

    voice = "alloy" if body.locale == "en" else "shimmer"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                _OPENAI_REALTIME_SESSIONS_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                    "OpenAI-Beta": "realtime=v1",
                },
                json={
                    "model": settings.openai_realtime_model,
                    "voice": voice,
                },
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        logger.warning(
            "OpenAI realtime session mint failed",
            error=str(exc),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not start voice session. Please try again.",
        ) from exc

    client_secret_obj = payload.get("client_secret") or {}
    client_secret = client_secret_obj.get("value")
    expires_at_epoch = client_secret_obj.get("expires_at")
    openai_session_id = payload.get("id")
    if not client_secret or not expires_at_epoch:
        logger.warning(
            "OpenAI realtime session response missing fields",
            payload_keys=list(payload.keys()),
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid voice session response.",
        )

    voice_session = TutorVoiceSession(
        id=uuid.uuid4(),
        user_id=current_user.id,
        openai_session_id=openai_session_id,
        started_at=datetime.utcnow(),
    )
    db.add(voice_session)
    await db.commit()

    expires_at = datetime.utcfromtimestamp(int(expires_at_epoch))

    return VoiceSessionResponse(
        session_id=voice_session.id,
        openai_session_id=openai_session_id,
        client_secret=client_secret,
        expires_at=expires_at,
        model=settings.openai_realtime_model,
        minutes_used_today=used,
        minutes_cap_per_day=cap,
    )


@router.post("/voice-session/close", response_model=VoiceSessionCloseResponse)
async def close_voice_session(
    body: VoiceSessionCloseRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> VoiceSessionCloseResponse:
    """Record the final duration of a voice session so the daily cap is accurate."""
    result = await db.execute(
        select(TutorVoiceSession).where(
            TutorVoiceSession.id == body.session_id,
            TutorVoiceSession.user_id == current_user.id,
        )
    )
    session_row = result.scalar_one_or_none()
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice session not found",
        )

    # Cap reported duration at a sane upper bound so a broken client cannot
    # lock a user out of the feature for the day.
    max_seconds = get_settings().tutor_voice_daily_minutes_cap * 60
    session_row.duration_seconds = max(0, min(body.duration_seconds, max_seconds))
    session_row.ended_at = session_row.started_at + timedelta(seconds=session_row.duration_seconds)
    await db.commit()

    used = await _minutes_used_today(current_user.id, db)
    cap = get_settings().tutor_voice_daily_minutes_cap
    return VoiceSessionCloseResponse(
        minutes_used_today=used,
        minutes_cap_per_day=cap,
    )
