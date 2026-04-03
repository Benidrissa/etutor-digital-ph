"""Pydantic schemas for courses and enrollment endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CourseCreateRequest(BaseModel):
    slug: str = Field(..., min_length=2, max_length=100)
    title_fr: str = Field(..., min_length=2)
    title_en: str = Field(..., min_length=2)
    description_fr: str | None = None
    description_en: str | None = None
    domain: str | None = None
    target_audience: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["fr", "en"])
    estimated_hours: int = Field(default=20, ge=1)
    cover_image_url: str | None = None


class CourseUpdateRequest(BaseModel):
    title_fr: str | None = None
    title_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
    domain: str | None = None
    target_audience: str | None = None
    languages: list[str] | None = None
    estimated_hours: int | None = Field(default=None, ge=1)
    cover_image_url: str | None = None
    status: str | None = None


class CourseResponse(BaseModel):
    id: uuid.UUID
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    domain: str | None
    target_audience: str | None
    languages: list[str] | None
    estimated_hours: int
    module_count: int
    status: str
    cover_image_url: str | None
    created_by: uuid.UUID | None
    rag_collection_id: str | None
    created_at: datetime
    published_at: datetime | None

    model_config = {"from_attributes": True}


class CourseListResponse(BaseModel):
    courses: list[CourseResponse]
    total: int


class EnrollmentRequest(BaseModel):
    course_id: uuid.UUID


class EnrollmentResponse(BaseModel):
    user_id: uuid.UUID
    course_id: uuid.UUID
    enrolled_at: datetime
    status: str
    completion_pct: float

    model_config = {"from_attributes": True}


class AgentGenerateRequest(BaseModel):
    domain: str
    target_audience: str | None = None
    languages: list[str] = Field(default_factory=lambda: ["fr", "en"])
    source_documents: list[str] = Field(
        default_factory=list,
        description="List of rag_collection_id entries or source names to use",
    )


class ModuleDraftResponse(BaseModel):
    module_number: int
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    estimated_hours: int
    bloom_level: str | None
    status: str
