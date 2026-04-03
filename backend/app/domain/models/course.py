from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module
    from app.domain.models.user import User


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    title_fr: Mapped[str] = mapped_column(Text, nullable=False)
    title_en: Mapped[str] = mapped_column(Text, nullable=False)
    description_fr: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str | None] = mapped_column(String)
    target_audience: Mapped[str | None] = mapped_column(Text)
    languages: Mapped[str] = mapped_column(String, server_default="fr,en")
    estimated_hours: Mapped[int] = mapped_column(Integer, server_default="0")
    module_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String, server_default="draft")
    cover_image_url: Mapped[str | None] = mapped_column(String)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rag_collection_id: Mapped[str | None] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped[User | None] = relationship("User", foreign_keys=[created_by], lazy="select")
    modules: Mapped[list[Module]] = relationship("Module", back_populates="course")
    enrollments: Mapped[list[UserCourseEnrollment]] = relationship(
        "UserCourseEnrollment", back_populates="course"
    )


class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String, server_default="active")
    completion_pct: Mapped[float] = mapped_column(server_default="0.0")

    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course"),)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
    course: Mapped[Course] = relationship("Course", back_populates="enrollments")
