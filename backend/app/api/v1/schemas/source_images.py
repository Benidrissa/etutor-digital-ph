"""Pydantic V2 schemas for source image API endpoints."""

from uuid import UUID

from pydantic import BaseModel, Field


class SourceImageMetadataResponse(BaseModel):
    id: UUID
    source: str
    rag_collection_id: str | None = None
    figure_number: str | None = None
    caption: str | None = None
    attribution: str | None = None
    image_type: str
    page_number: int
    chapter: str | None = None
    width: int | None = None
    height: int | None = None
    storage_url: str | None = None
    alt_text_fr: str | None = None
    alt_text_en: str | None = None

    model_config = {"from_attributes": True}


class SourceImageListResponse(BaseModel):
    items: list[SourceImageMetadataResponse] = Field(..., description="Source images")
    total: int = Field(..., description="Total count")
