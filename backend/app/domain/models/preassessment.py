from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course


class CoursePreassessment(Base):
    """Pre-assessment configuration and question bank for a course."""

    __tablename__ = "course_preassessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )

    preassessment_enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    mandatory: Mapped[bool] = mapped_column(Boolean, server_default="false")

    questions: Mapped[list] = mapped_column(JSONB)
    answer_key: Mapped[dict] = mapped_column(JSONB)
    question_levels: Mapped[dict] = mapped_column(JSONB)

    time_limit_minutes: Mapped[int] = mapped_column(Integer, server_default="30")
    retake_cooldown_days: Mapped[int] = mapped_column(Integer, server_default="90")

    instructions_fr: Mapped[str | None] = mapped_column(Text)
    instructions_en: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    course: Mapped[Course] = relationship("Course")
