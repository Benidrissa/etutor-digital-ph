"""Placement test API schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class PlacementTestQuestion(BaseModel):
    """Individual placement test question."""

    id: str = Field(..., description="Question identifier")
    domain: str = Field(..., description="Question domain/category")
    level: int = Field(..., ge=1, le=4, description="Curriculum level this question assesses (1-4)")
    question: str = Field(..., description="Question text")
    options: list[dict[str, str]] = Field(..., description="Answer options")
    # Note: correct_answer is NOT included in the response for security


class PlacementTestDomain(BaseModel):
    """Domain information for placement test."""

    name: dict[str, str] = Field(..., description="Domain name in multiple languages")
    questions: list[int] = Field(..., description="List of question IDs in this domain")


class PlacementTestResponse(BaseModel):
    """Placement test questions and metadata."""

    questions: list[PlacementTestQuestion] = Field(..., description="Test questions")
    total_questions: int = Field(..., description="Total number of questions")
    time_limit_minutes: int = Field(..., description="Time limit in minutes")
    instructions: dict[str, str] = Field(..., description="Instructions in multiple languages")
    domains: dict[str, PlacementTestDomain] = Field(..., description="Domain information")


class PlacementTestSubmission(BaseModel):
    """Placement test submission from user."""

    answers: dict[str, str] = Field(..., description="User answers: question_id -> selected_option")
    time_taken_sec: int = Field(..., ge=1, description="Time taken in seconds")


class PlacementTestResult(BaseModel):
    """Placement test result and level assignment."""

    assigned_level: int = Field(..., ge=1, le=4, description="Assigned level (1-4)")
    score_percentage: float = Field(..., ge=0.0, le=100.0, description="Overall score percentage")
    competency_areas: list[str] = Field(..., description="Identified strong competency areas")
    recommendations: list[str] = Field(..., description="Learning path recommendations")
    level_description: dict[str, str] = Field(
        ..., description="Level description in multiple languages"
    )
    can_retake_after: str = Field(..., description="When user can retake (ISO datetime)")
    skipped: bool = Field(default=False, description="Whether the test was skipped")


class PlacementTestAttemptResponse(BaseModel):
    """Persisted placement test attempt returned from the database."""

    id: str = Field(..., description="Attempt UUID")
    assigned_level: int = Field(..., ge=1, le=4, description="Assigned level (1-4)")
    raw_score: float = Field(..., ge=0.0, le=100.0, description="Raw percentage score")
    adjusted_score: float = Field(..., ge=0.0, le=100.0, description="Adjusted percentage score")
    domain_scores: dict[str, float] = Field(..., description="Per-level scores")
    competency_areas: list[str] = Field(..., description="Strong competency areas identified")
    recommendations: list[str] = Field(..., description="Learning path recommendations")
    attempted_at: datetime = Field(..., description="When the test was taken")
    can_retake_after: datetime | None = Field(None, description="When the user can retake")
