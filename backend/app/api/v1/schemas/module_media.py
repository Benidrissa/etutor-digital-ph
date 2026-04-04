"""Schemas for module media (audio/video summary) endpoints."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

MediaType = Literal["audio_summary", "video_summary"]
MediaStatus = Literal["pending", "generating", "ready", "failed"]


class ModuleMediaResponse(BaseModel):
    """Single module media record."""

    id: UUID = Field(..., description="Unique media identifier")
    module_id: UUID = Field(..., description="Associated module ID")
    media_type: MediaType = Field(..., description="Type of media (audio_summary|video_summary)")
    language: str = Field(..., description="Language code (fr|en)")
    status: MediaStatus = Field(..., description="Generation status")
    url: str | None = Field(
        None,
        description="URL to access the media — present only when status='ready'",
    )
    duration_seconds: int | None = Field(None, description="Media duration in seconds")
    file_size_bytes: int | None = Field(None, description="File size in bytes")
    mime_type: str | None = Field(None, description="MIME type (audio/mpeg, video/mp4, etc.)")
    generated_at: datetime | None = Field(None, description="When media was generated")
    created_at: datetime = Field(..., description="When the record was created")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440020",
                "module_id": "550e8400-e29b-41d4-a716-446655440001",
                "media_type": "audio_summary",
                "language": "fr",
                "status": "ready",
                "url": "/api/v1/modules/550e8400-e29b-41d4-a716-446655440001/media/550e8400-e29b-41d4-a716-446655440020/data",
                "duration_seconds": 420,
                "file_size_bytes": 3500000,
                "mime_type": "audio/mpeg",
                "generated_at": "2026-04-04T10:00:00",
                "created_at": "2026-04-04T09:55:00",
            }
        },
    }


class ModuleMediaListResponse(BaseModel):
    """List of media for a module."""

    module_id: UUID = Field(..., description="Module ID")
    media: list[ModuleMediaResponse] = Field(..., description="All media for this module")
    total: int = Field(..., description="Total number of media records")

    model_config = {"from_attributes": True}


class GenerateMediaRequest(BaseModel):
    """Request body for triggering media generation."""

    media_type: MediaType = Field(..., description="Type of media to generate")
    language: str = Field(..., description="Language code (fr|en)", pattern="^(fr|en)$")
    force_regenerate: bool = Field(
        False,
        description="Re-generate even if media already exists",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "media_type": "audio_summary",
                "language": "fr",
                "force_regenerate": False,
            }
        }
    }


class GenerateMediaResponse(BaseModel):
    """Response after triggering media generation."""

    media_id: UUID = Field(..., description="Media record ID")
    task_id: str | None = Field(None, description="Celery task ID for polling")
    status: MediaStatus = Field(..., description="Current status (pending if newly triggered)")
    message: str = Field(..., description="Human-readable message")

    model_config = {
        "json_schema_extra": {
            "example": {
                "media_id": "550e8400-e29b-41d4-a716-446655440020",
                "task_id": "celery-task-abc123",
                "status": "pending",
                "message": "Audio summary generation started",
            }
        }
    }


class MediaStatusResponse(BaseModel):
    """Lightweight status for polling."""

    media_id: UUID = Field(..., description="Media identifier")
    status: MediaStatus = Field(..., description="Current generation status")
    url: str | None = Field(None, description="URL — present only when status='ready'")

    model_config = {"from_attributes": True}
