from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course_resource import CourseResource
    from app.domain.models.module import Module
    from app.domain.models.preassessment import CoursePreAssessment
    from app.domain.models.taxonomy import TaxonomyCategory


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    title_fr: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    description_fr: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[str] = mapped_column(String, server_default="fr,en")
    estimated_hours: Mapped[int] = mapped_column(server_default="20")
    module_count: Mapped[int] = mapped_column(server_default="0")
    status: Mapped[str] = mapped_column(
        Enum("draft", "published", "archived", name="coursestatus"), server_default="draft"
    )
    cover_image_url: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rag_collection_id: Mapped[str | None] = mapped_column(String)
    indexation_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    syllabus_task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    syllabus_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    creation_step: Mapped[str] = mapped_column(String(20), server_default="upload", nullable=False)
    preassessment_enabled: Mapped[bool] = mapped_column(server_default="false")
    preassessment_mandatory: Mapped[bool] = mapped_column(server_default="false")
    syllabus_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    modules: Mapped[list[Module]] = relationship(back_populates="course")
    enrollments: Mapped[list[UserCourseEnrollment]] = relationship(back_populates="course")
    resources: Mapped[list[CourseResource]] = relationship(back_populates="course")
    taxonomy_categories: Mapped[list[TaxonomyCategory]] = relationship(
        secondary="course_taxonomy", lazy="selectin"
    )
    preassessments: Mapped[list[CoursePreAssessment]] = relationship(back_populates="course")


class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollment"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "dropped", name="enrollmentstatus"),
        server_default="active",
    )
    completion_pct: Mapped[float] = mapped_column(server_default="0.0")

    course: Mapped[Course] = relationship(back_populates="enrollments")
