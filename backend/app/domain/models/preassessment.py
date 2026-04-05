"""SQLAlchemy model for course pre-assessments."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course


class CoursePreAssessment(Base):
    __tablename__ = "course_preassessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False, server_default="fr")
    questions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    sources_cited: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    generated_by: Mapped[str] = mapped_column(String(50), nullable=False, server_default="ai")
    generation_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    course: Mapped[Course] = relationship("Course", back_populates="preassessments")
