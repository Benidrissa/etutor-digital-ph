"""Progress API schemas."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class LessonAccessRequest(BaseModel):
    """Request to record a lesson access/reading event."""

    module_id: UUID = Field(description="Module UUID")
    lesson_id: UUID = Field(description="Generated content ID for the lesson")
    time_spent_seconds: int = Field(description="Seconds spent reading so far", ge=0, default=0)
    completion_percentage: float = Field(
        description="Scroll/reading completion percentage (0-100)",
        ge=0.0,
        le=100.0,
        default=0.0,
    )


class ModuleProgressResponse(BaseModel):
    """Progress for a single module."""

    module_id: UUID = Field(description="Module UUID")
    user_id: UUID = Field(description="User UUID")
    module_number: int | None = Field(default=None, description="Module number (1-15)")
    status: str = Field(description="locked | in_progress | completed")
    completion_pct: float = Field(description="Completion percentage (0-100)")
    quiz_score_avg: float | None = Field(description="Average quiz score (0-100)")
    time_spent_minutes: int = Field(description="Total minutes spent")
    last_accessed: str | None = Field(description="ISO timestamp of last access")


class UnitProgressDetail(BaseModel):
    """Progress detail for a single unit within a module."""

    id: str = Field(description="Unit number/ID")
    unit_number: str = Field(description="Unit number e.g. M01-U01")
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_minutes: int
    order_index: int
    status: str = Field(description="pending | in_progress | completed")


class ModuleDetailWithProgressResponse(BaseModel):
    """Module detail including units and progress."""

    id: str = Field(description="Module UUID")
    module_number: int
    level: int
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    estimated_hours: int
    prereq_modules: list[str] = Field(default_factory=list)
    status: str = Field(description="locked | in_progress | completed")
    completion_pct: float
    quiz_score_avg: float | None = None
    time_spent_minutes: int = 0
    last_accessed: str | None = None
    units: list[UnitProgressDetail] = Field(default_factory=list)


class CompleteLessonRequest(BaseModel):
    """Request to mark a lesson/unit as completed (requires passing quiz)."""

    module_id: UUID = Field(description="Module UUID")
    unit_id: str = Field(description="Unit ID, e.g. 'M01-U02'")


class CompleteLessonResponse(BaseModel):
    """Response after attempting to complete a lesson."""

    completed: bool = Field(description="Whether the lesson was marked as completed")
    module_progress: ModuleProgressResponse


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    message: str
