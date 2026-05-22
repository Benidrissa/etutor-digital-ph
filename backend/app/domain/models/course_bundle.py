"""CourseBundle model — tracks ZIP bundle export jobs per course."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course
    from app.domain.models.user import User


class CourseBundle(Base):
    """One ZIP bundle export job per (course, language, requested_by) request.

    The Celery task generates a flat ZIP of self-contained HTML files
    (one per unit × content_type, images + audio embedded as base64)
    and uploads it to MinIO.  Polling endpoints read `status` and
    `task_id` to surface progress to the frontend.
    """

    __tablename__ = "course_bundles"
    __table_args__ = (
        Index("ix_course_bundles_course_id", "course_id"),
        Index("ix_course_bundles_status", "status"),
        Index("ix_course_bundles_requested_by", "requested_by"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    language: Mapped[str] = mapped_column(String(2), nullable=False)  # "fr" | "en"
    level: Mapped[int] = mapped_column(SmallInteger, server_default="1", nullable=False)
    country: Mapped[str] = mapped_column(String(4), server_default="SN", nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Enum(
            "pending",
            "generating",
            "ready",
            "failed",
            name="bundlestatus",
            create_type=False,
        ),
        server_default="pending",
        nullable=False,
    )
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_count: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    course: Mapped[Course] = relationship("Course")
    requester: Mapped[User | None] = relationship("User", foreign_keys=[requested_by])
