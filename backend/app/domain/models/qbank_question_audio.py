"""QBank question audio model for TTS audio per question per language."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

if TYPE_CHECKING:
    pass


class QBankQuestionAudio(Base):
    __tablename__ = "qbank_question_audio"
    __table_args__ = (
        Index("ix_qbank_question_audio_question_id", "question_id"),
        Index("ix_qbank_question_audio_status", "status"),
        sa.UniqueConstraint(
            "question_id",
            "language",
            name="uq_qbank_question_audio_question_lang",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(),
        nullable=False,
    )
    language: Mapped[str] = mapped_column(String(10), server_default="fr")
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_manual_upload: Mapped[bool] = mapped_column(sa.Boolean, server_default="false")
    status: Mapped[str] = mapped_column(
        sa.Enum(
            "pending",
            "generating",
            "ready",
            "failed",
            name="qbank_audio_status_enum",
            create_type=True,
        ),
        server_default="pending",
    )
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
