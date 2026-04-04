from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index, Integer, String, Text, func
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
        Index("ix_module_media_module_id", "module_id"),
        Index("ix_module_media_status", "status"),
        Index("ix_module_media_module_language_type", "module_id", "language", "media_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="audio_summary",
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.Enum("pending", "generating", "ready", "failed", name="media_status_enum"),
        server_default="pending",
        nullable=False,
    )
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    module: Mapped[Module] = relationship("Module", foreign_keys=[module_id])
