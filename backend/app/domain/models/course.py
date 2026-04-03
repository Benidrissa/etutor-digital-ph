from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module
    from app.domain.models.user import User


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
    languages: Mapped[list[str] | None] = mapped_column(ARRAY(String), server_default="{}")
    estimated_hours: Mapped[int] = mapped_column(Integer, server_default="20")
    module_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String, server_default="draft")
    cover_image_url: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    rag_collection_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    modules: Mapped[list[Module]] = relationship(back_populates="course")
    enrollments: Mapped[list[UserCourseEnrollment]] = relationship(back_populates="course")


class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), primary_key=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String, server_default="active")
    completion_pct: Mapped[float] = mapped_column(Float, server_default="0.0")

    user: Mapped[User] = relationship(back_populates="course_enrollments")
    course: Mapped[Course] = relationship(back_populates="enrollments")
