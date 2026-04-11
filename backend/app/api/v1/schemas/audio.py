"""Schemas for lesson audio status endpoints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AudioStatus = Literal["pending", "generating", "ready", "failed"]


class LessonAudioResponse(BaseModel):
    """Single audio record for a lesson."""

    audio_id: UUID = Field(..., description="Unique audio identifier")
    lesson_id: UUID = Field(..., description="Associated lesson ID")
    status: AudioStatus = Field(..., description="Audio generation status")
    audio_url: str | None = Field(
        None,
        description="Public audio URL — present only when status='ready'",
    )
    duration_seconds: int | None = Field(None, description="Audio duration in seconds")
    file_size_bytes: int | None = Field(None, description="Audio file size in bytes")


class LessonAudioListResponse(BaseModel):
    """List of audio files for a lesson."""

    lesson_id: UUID = Field(..., description="Lesson ID")
    audio: list[LessonAudioResponse] = Field(..., description="Audio files for the lesson")
    total: int = Field(..., description="Total number of audio files")


class AudioStatusResponse(BaseModel):
    """Lightweight audio status for polling."""

    audio_id: UUID = Field(..., description="Audio identifier")
    status: AudioStatus = Field(..., description="Current generation status")
    audio_url: str | None = Field(
        None,
        description="Public audio URL — present only when status='ready'",
    )
    duration_seconds: int | None = Field(None, description="Audio duration in seconds")
