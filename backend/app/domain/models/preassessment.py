from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course


class CoursePreAssessment(Base):
    __tablename__ = "course_preassessments"
    __table_args__ = (
        UniqueConstraint("course_id", "language", name="uq_course_preassessments_course_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    language: Mapped[str] = mapped_column(String(2))
    questions: Mapped[list] = mapped_column(JSONB)
    answer_key: Mapped[dict] = mapped_column(JSONB)
    question_levels: Mapped[dict] = mapped_column(JSONB)
    domains: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(10), server_default="manual")
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    course: Mapped[Course] = relationship(back_populates="preassessments")
