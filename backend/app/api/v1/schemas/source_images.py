"""Pydantic schemas for source image API endpoints."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SourceImageMetadataResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    rag_collection_id: str | None = None
    figure_number: str | None = None
    caption: str | None = None
    attribution: str | None = None
    image_type: str
    page_number: int | None = None
    chapter: str | None = None
    width: int | None = None
    height: int | None = None
    file_size_bytes: int | None = None
    storage_url: str | None = None
    alt_text_fr: str | None = None
    alt_text_en: str | None = None


class SourceImageListResponse(BaseModel):
    items: list[SourceImageMetadataResponse]
    total: int
    page: int
    limit: int
    has_next: bool
