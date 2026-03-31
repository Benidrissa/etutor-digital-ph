"""Pydantic schemas for module endpoints."""

from typing import Any

from pydantic import BaseModel


class ModuleProgressSchema(BaseModel):
    """User progress for a specific module."""

    status: str  # "locked" | "unlocked" | "in_progress" | "completed"
    completion_pct: float  # 0-100
    quiz_score_avg: float | None  # 0-100, None if no quizzes taken
    time_spent_minutes: int
    last_accessed: str | None  # ISO datetime string


class ModuleSchema(BaseModel):
    """Module information with user progress."""

    id: str
    module_number: int  # 1-15
    level: int  # 1-4
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    estimated_hours: int
    bloom_level: str | None
    prereq_modules: list[str]  # Array of module UUIDs
    books_sources: dict[str, Any] | None
    progress: ModuleProgressSchema
    is_unlocked: bool


class ModuleListResponse(BaseModel):
    """Response for listing all modules with progress."""

    modules: list[ModuleSchema]


class PrerequisiteStatusSchema(BaseModel):
    """Status of a single prerequisite module."""

    module_id: str
    module_number: int | None
    title: str
    completion_pct: float  # Current completion percentage
    quiz_score_avg: float | None  # Current average quiz score
    completion_met: bool  # True if ≥80% completion
    quiz_score_met: bool  # True if ≥80% quiz score
    overall_met: bool  # True if both completion and quiz score requirements met


class ModuleUnlockStatusResponse(BaseModel):
    """Detailed unlock status for a specific module."""

    module_id: str
    is_unlocked: bool
    current_status: str  # Current progress status
    prerequisites: list[PrerequisiteStatusSchema]  # Empty list if no prerequisites
