"""Schemas for image status endpoints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ImageStatus = Literal["pending", "generating", "ready", "failed"]


class LessonImageResponse(BaseModel):
    """Single image record for a lesson."""

    image_id: UUID = Field(..., description="Unique image identifier")
    lesson_id: UUID = Field(..., description="Associated lesson ID")
    status: ImageStatus = Field(..., description="Image generation status")
    image_url: str | None = Field(
        None,
        description="Public image URL — present only when status='ready', null otherwise",
    )
    alt_text: str = Field(..., description="Localized alt text for accessibility")
    format: str = Field(default="webp", description="Image format (webp, png, jpeg)")
    width: int = Field(default=800, description="Image width in pixels")

    model_config = {
        "json_schema_extra": {
            "example": {
                "image_id": "550e8400-e29b-41d4-a716-446655440010",
                "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                "status": "ready",
                "image_url": "https://cdn.example.com/images/550e8400.webp",
                "alt_text": "Diagramme illustrant la surveillance épidémiologique",
                "format": "webp",
                "width": 800,
            }
        }
    }


class LessonImagesListResponse(BaseModel):
    """List of images for a lesson."""

    lesson_id: UUID = Field(..., description="Lesson ID")
    images: list[LessonImageResponse] = Field(..., description="Images for the lesson")
    total: int = Field(..., description="Total number of images")

    model_config = {
        "json_schema_extra": {
            "example": {
                "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                "images": [
                    {
                        "image_id": "550e8400-e29b-41d4-a716-446655440010",
                        "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                        "status": "ready",
                        "image_url": "https://cdn.example.com/images/550e8400.webp",
                        "alt_text": "Diagramme illustrant la surveillance épidémiologique",
                        "format": "webp",
                        "width": 800,
                    }
                ],
                "total": 1,
            }
        }
    }


class ImageStatusResponse(BaseModel):
    """Lightweight image status for polling."""

    image_id: UUID = Field(..., description="Image identifier")
    status: ImageStatus = Field(..., description="Current generation status")
    image_url: str | None = Field(
        None,
        description="Public image URL — present only when status='ready'",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "image_id": "550e8400-e29b-41d4-a716-446655440010",
                "status": "pending",
                "image_url": None,
            }
        }
    }
