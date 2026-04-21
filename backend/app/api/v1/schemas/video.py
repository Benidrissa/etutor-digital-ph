"""Schemas for lesson video status endpoints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

VideoStatus = Literal["pending", "generating", "ready", "failed"]


class LessonVideoResponse(BaseModel):
    """Single video record for a lesson."""

    video_id: UUID = Field(..., description="Unique video row identifier")
    lesson_id: UUID = Field(..., description="Associated lesson ID")
    status: VideoStatus = Field(..., description="Video generation status")
    video_url: str | None = Field(
        None,
        description="Public video URL — present only when status='ready'",
    )
    duration_seconds: int | None = Field(None, description="Video duration in seconds")
    file_size_bytes: int | None = Field(None, description="Video file size in bytes")


class LessonVideoListResponse(BaseModel):
    """List of video files for a lesson."""

    lesson_id: UUID = Field(..., description="Lesson ID")
    video: list[LessonVideoResponse] = Field(..., description="Video files for the lesson")
    total: int = Field(..., description="Total number of video files")


class VideoStatusResponse(BaseModel):
    """Lightweight video status for polling."""

    video_id: UUID = Field(..., description="Video row identifier")
    status: VideoStatus = Field(..., description="Current generation status")
    video_url: str | None = Field(
        None,
        description="Public video URL — present only when status='ready'",
    )
    duration_seconds: int | None = Field(None, description="Video duration in seconds")


class GenerateLessonVideoResponse(BaseModel):
    """Response to a lesson-video generation kickoff."""

    video_id: UUID = Field(..., description="Video row identifier")
    status: VideoStatus = Field(..., description="Status right after kickoff")
    message: str = Field(..., description="Human-readable status message")
