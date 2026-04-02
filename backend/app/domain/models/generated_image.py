from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module


class GeneratedImage(Base):
    __tablename__ = "generated_images"
    __table_args__ = (
        Index("ix_generated_images_semantic_tags_gin", "semantic_tags", postgresql_using="gin"),
        Index("ix_generated_images_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id", ondelete="SET NULL"),
        nullable=True,
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="SET NULL"),
        nullable=True,
    )
    unit_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    concept: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(String(20), server_default="webp")
    width: Mapped[int] = mapped_column(Integer, server_default="512")
    alt_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    reuse_count: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(
        sa.Enum("pending", "generating", "ready", "failed", name="image_status_enum"),
        server_default="pending",
    )
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    lesson: Mapped[GeneratedContent | None] = relationship(
        "GeneratedContent",
        foreign_keys=[lesson_id],
    )
    module: Mapped[Module | None] = relationship(
        "Module",
        foreign_keys=[module_id],
    )
