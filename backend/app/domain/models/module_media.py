from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module


class MediaType(enum.StrEnum):
    audio_summary = "audio_summary"
    video_summary = "video_summary"
    podcast_summary = "podcast_summary"


class MediaStatus(enum.StrEnum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class ModuleMedia(Base):
    __tablename__ = "module_media"
    __table_args__ = (
        UniqueConstraint(
            "module_id",
            "media_type",
            "language",
            name="uq_module_media_module_type_lang",
        ),
        Index("ix_module_media_module_id", "module_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    media_type: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(2))
    storage_key: Mapped[str] = mapped_column(String)
    storage_url: Mapped[str] = mapped_column(String)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    module: Mapped[Module] = relationship(back_populates="media")
