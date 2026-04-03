from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True)
    title_fr: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    description_fr: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String)
    target_audience: Mapped[str | None] = mapped_column(Text)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    modules: Mapped[list[Module]] = relationship(back_populates="course")
    enrollments: Mapped[list[UserCourseEnrollment]] = relationship(back_populates="course")


class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollment"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "dropped", name="enrollmentstatus"), server_default="active"
    )
    completion_pct: Mapped[float] = mapped_column(server_default="0.0")

    course: Mapped[Course] = relationship(back_populates="enrollments")
