"""Pydantic schemas for admin syllabus management endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ActivitySchema(BaseModel):
    quiz_topics: list[str] = Field(default_factory=list)
    flashcard_count: int = Field(default=20)
    case_study_scenario: str = Field(default="")


class ModuleDraftSchema(BaseModel):
    module_number: int | None = Field(None, ge=1, le=15)
    level: int = Field(..., ge=1, le=4)
    title_fr: str = Field(..., min_length=1, max_length=255)
    title_en: str = Field(..., min_length=1, max_length=255)
    description_fr: str | None = Field(None)
    description_en: str | None = Field(None)
    objectives_fr: list[str] = Field(default_factory=list)
    objectives_en: list[str] = Field(default_factory=list)
    key_contents_fr: list[str] = Field(default_factory=list)
    key_contents_en: list[str] = Field(default_factory=list)
    aof_context_fr: str | None = Field(None)
    aof_context_en: str | None = Field(None)
    activities: ActivitySchema = Field(default_factory=ActivitySchema)
    source_references: list[str] = Field(default_factory=list)
    estimated_hours: int = Field(default=20, ge=1, le=100)
    bloom_level: str | None = Field(None)
    prereq_modules: list[UUID] = Field(default_factory=list)
    books_sources: dict[str, Any] | None = Field(None)


class SyllabusAgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    module_id: UUID | None = Field(None)
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)


class ModuleCardResponse(BaseModel):
    id: UUID
    module_number: int
    level: int
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_hours: int
    bloom_level: str | None = None
    unit_count: int = 0
    source_references: list[str] = Field(default_factory=list)


class ModuleListResponse(BaseModel):
    modules: list[ModuleCardResponse]
    total: int


class ModuleSaveRequest(BaseModel):
    draft: ModuleDraftSchema


class ModuleSaveResponse(BaseModel):
    id: UUID
    module_number: int
    created: bool
    message: str


class AuditLogEntry(BaseModel):
    id: UUID
    admin_id: str
    admin_email: str
    action: str
    module_id: UUID | None = None
    module_number: int | None = None
    changes: dict[str, Any]
    created_at: datetime


class ModuleExportResponse(BaseModel):
    module_number: int
    markdown: str
