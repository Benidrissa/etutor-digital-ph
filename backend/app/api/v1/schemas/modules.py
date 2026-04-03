"""Schemas for module offline bundle API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OfflineBundleUnit(BaseModel):
    """A single unit entry in the offline bundle manifest."""

    unit_id: str = Field(description="Unit ID, e.g. M01-U01")
    unit_number: str = Field(description="Unit number string, e.g. M01-U01")
    order_index: int = Field(description="Display order within the module")
    title_fr: str
    title_en: str
    estimated_minutes: int
    size_bytes: int = Field(description="Estimated size in bytes for this unit")
    content_ids: dict[str, str | None] = Field(
        description="Map of content_type -> generated_content_id (or null if not cached)"
    )
    image_urls: list[str] = Field(default_factory=list, description="Image URLs for this unit")


class OfflineBundleResponse(BaseModel):
    """Response from GET /api/v1/modules/{id}/offline-bundle."""

    module_id: str = Field(description="Module UUID")
    module_number: int
    title_fr: str
    title_en: str
    total_size_bytes: int = Field(description="Estimated total download size in bytes")
    units: list[OfflineBundleUnit] = Field(description="Units available for offline download")
