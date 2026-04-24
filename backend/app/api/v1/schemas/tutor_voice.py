"""Pydantic schemas for tutor voice-output endpoints (#1932)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TutorMessageAudioResponse(BaseModel):
    """Status + URL for a per-message TTS clip."""

    status: Literal["pending", "generating", "ready", "failed"] = Field(
        ..., description="Lifecycle status of the audio record"
    )
    url: str | None = Field(None, description="Public URL of the audio asset (when ready)")
    duration_seconds: int | None = Field(None, description="Estimated audio duration in seconds")
    error_message: str | None = Field(None, description="Failure reason when status=failed")


class VoiceSessionRequest(BaseModel):
    """Request body for minting an OpenAI Realtime session token."""

    locale: Literal["fr", "en"] = Field("en", description="Voice call locale")


class VoiceSessionResponse(BaseModel):
    """Ephemeral credentials the browser uses to connect to OpenAI Realtime."""

    session_id: UUID = Field(..., description="Internal tutor_voice_sessions row id")
    openai_session_id: str | None = Field(None, description="OpenAI-side session id")
    client_secret: str = Field(..., description="Ephemeral token; goes in the Authorization header")
    expires_at: datetime = Field(..., description="UTC expiry of the ephemeral token")
    model: str = Field(..., description="Realtime model alias")
    minutes_used_today: int = Field(..., description="Voice minutes consumed so far today")
    minutes_cap_per_day: int = Field(..., description="Free-tier daily cap")


class VoiceSessionCloseRequest(BaseModel):
    """Client reports final duration when hanging up."""

    session_id: UUID = Field(..., description="Internal session id from /voice-session")
    duration_seconds: int = Field(..., ge=0, description="Reported call duration in seconds")


class VoiceSessionCloseResponse(BaseModel):
    """Acknowledgement after a voice session is closed."""

    minutes_used_today: int = Field(..., description="Cumulative voice minutes for today")
    minutes_cap_per_day: int = Field(..., description="Free-tier daily cap")
