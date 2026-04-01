"""Schemas for image status endpoints."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

ImageStatus = Literal["pending", "generating", "ready", "failed"]


class LessonImageResponse(BaseModel):
    """Single image entry for a lesson."""

    id: UUID = Field(..., description="Image ID")
    lesson_id: UUID = Field(..., description="Associated lesson ID")
    status: ImageStatus = Field(..., description="Image generation status")
    image_url: str | None = Field(
        None,
        description="Image URL — present only when status is 'ready'",
    )
    alt_text: str | None = Field(
        None,
        description="Localized alt text for accessibility",
    )
    format: str | None = Field(None, description="Image format (e.g. 'webp', 'png')")
    width: int | None = Field(None, description="Image width in pixels")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440010",
                "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                "status": "ready",
                "image_url": "https://cdn.example.com/images/550e8400.webp",
                "alt_text": "Diagramme du système de surveillance épidémiologique en Afrique de l'Ouest",
                "format": "webp",
                "width": 800,
            }
        }
    }


class LessonImagesListResponse(BaseModel):
    """List of images for a lesson."""

    lesson_id: UUID = Field(..., description="Lesson ID")
    images: list[LessonImageResponse] = Field(..., description="Images for this lesson")

    model_config = {
        "json_schema_extra": {
            "example": {
                "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                "images": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440010",
                        "lesson_id": "550e8400-e29b-41d4-a716-446655440001",
                        "status": "ready",
                        "image_url": "https://cdn.example.com/images/550e8400.webp",
                        "alt_text": "Diagramme du système de surveillance",
                        "format": "webp",
                        "width": 800,
                    }
                ],
            }
        }
    }


class ImageStatusResponse(BaseModel):
    """Lightweight image status for polling."""

    id: UUID = Field(..., description="Image ID")
    status: ImageStatus = Field(..., description="Image generation status")
    image_url: str | None = Field(
        None,
        description="Image URL — present only when status is 'ready'",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440010",
                "status": "generating",
                "image_url": None,
            }
        }
    }
