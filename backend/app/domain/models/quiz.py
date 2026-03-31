from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module
    from app.domain.models.user import User


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_content.id"), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float | None]
    time_taken_sec: Mapped[int | None] = mapped_column(Integer)
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="quiz_attempts")
    quiz: Mapped[GeneratedContent] = relationship(back_populates="quiz_attempts")


class SummativeAssessmentAttempt(Base):
    """Tracks summative assessment attempts with enhanced features."""

    __tablename__ = "summative_assessment_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id"), index=True)
    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_content.id"), index=True)

    # Assessment results
    answers: Mapped[dict] = mapped_column(JSON)  # All answers and metadata
    score: Mapped[float]  # Final score percentage (0-100)
    total_questions: Mapped[int] = mapped_column(default=20)
    correct_answers: Mapped[int]
    time_taken_sec: Mapped[int] = mapped_column(Integer)
    passed: Mapped[bool] = mapped_column(Boolean)  # True if score >= 80%

    # Domain breakdown - JSON structure: {"domain_name": {"correct": 3, "total": 5}}
    domain_breakdown: Mapped[dict] = mapped_column(JSON)

    # Progression tracking
    module_unlocked: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt_number: Mapped[int] = mapped_column(Integer)  # 1, 2, 3, etc.
    can_retry_at: Mapped[datetime | None]  # When user can retry (24h cooldown)

    # Timestamps
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    user: Mapped[User] = relationship(back_populates="summative_attempts")
    module: Mapped[Module] = relationship(back_populates="summative_attempts")
    assessment: Mapped[GeneratedContent] = relationship(back_populates="summative_attempts")


class PlacementTestAttempt(Base):
    """Tracks placement test attempts for level assignment."""

    __tablename__ = "placement_test_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)

    # Assessment results
    answers: Mapped[dict] = mapped_column(JSON)  # All answers: {"1": "a", "2": "b", ...}
    raw_score: Mapped[float]  # Raw percentage score (0-100)
    adjusted_score: Mapped[float]  # Adjusted score after context factors
    assigned_level: Mapped[int]  # Level assigned (1-4)
    time_taken_sec: Mapped[int] = mapped_column(Integer)

    # Domain breakdown - JSON structure: {"basic_public_health": 80.0, "epidemiology": 60.0, ...}
    domain_scores: Mapped[dict] = mapped_column(JSON)

    # User context used for scoring
    user_context: Mapped[dict] = mapped_column(JSON)  # Role, country, experience, etc.

    # Competencies and recommendations
    competency_areas: Mapped[list] = mapped_column(JSON)  # Strong areas identified
    recommendations: Mapped[list] = mapped_column(JSON)  # Learning path suggestions

    # Restriction tracking (3-month re-test limit)
    can_retake_after: Mapped[datetime | None]  # When user can retake (3 months later)

    # Timestamps
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationship
    user: Mapped[User] = relationship(back_populates="placement_attempts")
