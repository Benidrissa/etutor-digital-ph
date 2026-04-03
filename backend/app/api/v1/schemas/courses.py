"""Pydantic schemas for course catalog and enrollment endpoints."""

from pydantic import BaseModel, Field


class CourseCreateRequest(BaseModel):
    slug: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$")
    title_fr: str = Field(..., min_length=3, max_length=200)
    title_en: str = Field(..., min_length=3, max_length=200)
    description_fr: str | None = None
    description_en: str | None = None
    domain: str | None = None
    target_audience: str | None = None
    languages: str = "fr,en"
    estimated_hours: int = Field(default=0, ge=0)
    cover_image_url: str | None = None


class CourseUpdateRequest(BaseModel):
    title_fr: str | None = Field(None, min_length=3, max_length=200)
    title_en: str | None = Field(None, min_length=3, max_length=200)
    description_fr: str | None = None
    description_en: str | None = None
    domain: str | None = None
    target_audience: str | None = None
    languages: str | None = None
    estimated_hours: int | None = Field(None, ge=0)
    cover_image_url: str | None = None


class CourseResponse(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    domain: str | None
    target_audience: str | None
    languages: str
    estimated_hours: int
    module_count: int
    status: str
    cover_image_url: str | None
    created_by: str | None
    rag_collection_id: str | None
    created_at: str
    published_at: str | None


class EnrollmentResponse(BaseModel):
    user_id: str
    course_id: str
    enrolled_at: str
    status: str
    completion_pct: float


class AgentGenerateRequest(BaseModel):
    domain: str = Field(..., min_length=2)
    target_audience: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
