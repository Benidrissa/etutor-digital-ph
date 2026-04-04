"""Taxonomy categories for course classification (domain, level, audience)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class TaxonomyCategory(Base):
    __tablename__ = "taxonomy_categories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(20))  # 'domain' | 'level' | 'audience'
    slug: Mapped[str] = mapped_column(String(100))
    label_fr: Mapped[str] = mapped_column(Text)
    label_en: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        # Unique slug per type
        {"comment": "CHECK(type IN ('domain', 'level', 'audience'))"},
    )


class CourseTaxonomy(Base):
    __tablename__ = "course_taxonomy"

    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("taxonomy_categories.id", ondelete="RESTRICT"), primary_key=True
    )
