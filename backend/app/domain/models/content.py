from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSON, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course_quality import CourseQualityRun
    from app.domain.models.flashcard import FlashcardReview
    from app.domain.models.module import Module
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.models.quiz import QuizAttempt, SummativeAssessmentAttempt


class GeneratedContent(Base):
    __tablename__ = "generated_content"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), index=True
    )
    # FK to module_units; nullable because flashcards and summative quizzes
    # are intentionally module-scoped (no unit binding). For unit-scoped
    # content this is the authoritative join — replaces the legacy
    # JSON-string match on content->>'unit_id' (issue #2007 / migration 084).
    module_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("module_units.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    content_type: Mapped[str] = mapped_column(String, index=True)  # lesson|quiz|flashcard|case
    language: Mapped[str] = mapped_column(String(2), index=True)  # fr|en
    level: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    sources_cited: Mapped[list | None] = mapped_column(JSON)
    country_context: Mapped[str | None] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    validated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_manually_edited: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Quality agent state (#2215). `validated` above remains the
    # human-override flag; `quality_status` is the agent's state.
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), server_default="pending")
    quality_flags: Mapped[list] = mapped_column(JSONB, server_default="[]")
    quality_assessed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    regeneration_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    last_quality_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("course_quality_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    content_revision: Mapped[int] = mapped_column(SmallInteger, server_default="1")

    module: Mapped[Module] = relationship(back_populates="generated_content")
    module_unit: Mapped[ModuleUnit | None] = relationship(back_populates="generated_content")
    quiz_attempts: Mapped[list[QuizAttempt]] = relationship(
        back_populates="quiz", passive_deletes=True
    )
    summative_attempts: Mapped[list[SummativeAssessmentAttempt]] = relationship(
        back_populates="assessment", passive_deletes=True
    )
    flashcard_reviews: Mapped[list[FlashcardReview]] = relationship(
        back_populates="card", passive_deletes=True
    )
    last_quality_run: Mapped[CourseQualityRun | None] = relationship(
        foreign_keys=[last_quality_run_id]
    )
