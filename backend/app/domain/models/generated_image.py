from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module


class ImageStatus(enum.StrEnum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("generated_content.id"), nullable=True
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("modules.id"), nullable=True
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
    status: Mapped[ImageStatus] = mapped_column(
        Enum(ImageStatus, name="imagestatus"), server_default="pending"
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    lesson: Mapped[GeneratedContent | None] = relationship(
        "GeneratedContent", foreign_keys=[lesson_id]
    )
    module: Mapped[Module | None] = relationship("Module", foreign_keys=[module_id])

    __table_args__ = (
        Index("ix_generated_images_status", "status"),
        Index("ix_generated_images_semantic_tags", "semantic_tags", postgresql_using="gin"),
    )
