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
