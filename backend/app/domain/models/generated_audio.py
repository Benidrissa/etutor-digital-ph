"""Generated audio model for lesson audio summaries."""

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


class GeneratedAudio(Base):
    """Per-lesson media cache — audio today, video too after #1802.

    Despite the legacy name, this table holds both audio summaries
    and (via the ``media_type`` discriminator) HeyGen-rendered video
    summaries, so the poller, finalizer, and status endpoints can
    treat both kinds symmetrically. Table rename is a cosmetic
    follow-up.
    """

    __tablename__ = "generated_audio"
    __table_args__ = (
        Index("ix_generated_audio_lesson_id", "lesson_id"),
        Index("ix_generated_audio_status", "status"),
        sa.UniqueConstraint(
            "module_id",
            "unit_id",
            "media_type",
            "language",
            name="uq_generated_audio_module_unit_mediatype_lang",
        ),
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
    language: Mapped[str] = mapped_column(String(5), server_default="fr")
    # "audio" | "video" — written by the migration's server_default,
    # so pre-existing rows read back as "audio" without a backfill.
    media_type: Mapped[str] = mapped_column(
        String(20),
        server_default="audio",
        nullable=False,
    )
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    script_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Populated only for media_type="video": HeyGen's async job id so
    # the Celery poller can correlate status events back to this row.
    provider_video_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Video-row metadata: {"api_version": "v2"|"v3-agent", "is_kids": bool}.
    # Unused for audio, kept nullable for future extension.
    media_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        sa.Enum(
            "pending",
            "generating",
            "ready",
            "failed",
            name="audio_status_enum",
            create_type=False,
        ),
        server_default="pending",
    )
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    lesson: Mapped[GeneratedContent | None] = relationship(
        "GeneratedContent",
        foreign_keys=[lesson_id],
    )
    module: Mapped[Module | None] = relationship(
        "Module",
        foreign_keys=[module_id],
    )
