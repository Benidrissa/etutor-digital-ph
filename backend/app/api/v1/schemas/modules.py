"""Schemas for modules API endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class UnitBundleSchema(BaseModel):
    """A single unit's content bundle for offline use."""

    unit_id: str = Field(description="Unit identifier e.g. M01-U01")
    unit_number: str
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_minutes: int
    order_index: int
    lesson_content_id: str | None = Field(
        None, description="Generated lesson content ID (if cached)"
    )
    quiz_content_id: str | None = Field(None, description="Generated quiz content ID (if cached)")
    case_study_content_id: str | None = Field(
        None, description="Generated case study content ID (if cached)"
    )


class ModuleOfflineBundleResponse(BaseModel):
    """Full offline bundle for a module."""

    module_id: str = Field(description="Module UUID")
    module_number: int
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_hours: int
    level: int
    units: list[UnitBundleSchema] = Field(default_factory=list)
    estimated_size_bytes: int = Field(description="Estimated download size in bytes")
    cached_content_count: int = Field(description="Number of content items already cached in DB")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    message: str
