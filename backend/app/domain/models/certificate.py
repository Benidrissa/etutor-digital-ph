from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course
    from app.domain.models.user import User


class CertificateTemplate(Base):
    __tablename__ = "certificate_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True, index=True
    )
    title_fr: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    organization_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    signatory_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    signatory_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    additional_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    course: Mapped[Course] = relationship(back_populates="certificate_template")
    certificates: Mapped[list[Certificate]] = relationship(back_populates="template")


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_certificate_user_course"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("certificate_templates.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    verification_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    average_score: Mapped[float]
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pdf_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        postgresql.ENUM("valid", "revoked", name="certificatestatus", create_type=False),
        server_default="valid",
    )
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    template: Mapped[CertificateTemplate | None] = relationship(back_populates="certificates")
    user: Mapped[User] = relationship(back_populates="certificates")
    course: Mapped[Course] = relationship(back_populates="certificates")
