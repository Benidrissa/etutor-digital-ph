"""Schemas for module units endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ModuleUnitResponse(BaseModel):
    """Response schema for a single module unit."""

    id: uuid.UUID
    module_id: uuid.UUID
    unit_number: str
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_minutes: int
    order_index: int
    unit_type: Literal["lesson", "quiz", "case-study"] = "lesson"
    books_sources: dict[str, Any] | None = None

    model_config = {"from_attributes": True}


class ModuleUnitsResponse(BaseModel):
    """Response schema for list of units belonging to a module."""

    module_id: uuid.UUID
    units: list[ModuleUnitResponse]
    total: int


class UnitCreateRequest(BaseModel):
    """Request schema for creating a new unit (admin only)."""

    unit_number: str = Field(..., max_length=10)
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_minutes: int = Field(default=45, ge=5, le=300)
    order_index: int = Field(..., ge=1)
    unit_type: Literal["lesson", "quiz", "case-study"] = "lesson"
    books_sources: dict[str, Any] | None = None


class UnitUpdateRequest(BaseModel):
    """Request schema for updating a unit (admin only)."""

    title_fr: str | None = None
    title_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=300)
    order_index: int | None = Field(default=None, ge=1)
    unit_type: Literal["lesson", "quiz", "case-study"] | None = None
    books_sources: dict[str, Any] | None = None
