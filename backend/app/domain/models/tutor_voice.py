"""Models backing the hybrid tutor voice-output feature (#1932).

Two concerns split across two tables:

* ``TutorMessageAudio`` — per-message TTS cache for the "listen" button.
  Keyed on (conversation_id, message_index, language) because tutor messages
  are positional entries in ``tutor_conversations.messages`` JSON and carry
  no per-message UUID.
* ``TutorVoiceSession`` — audit log of live voice-call sessions, used to
  enforce ``tutor_voice_daily_minutes_cap`` across sessions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.conversation import TutorConversation
    from app.domain.models.user import User


class TutorMessageAudio(Base):
    """Cached TTS audio for a single tutor reply in a conversation."""

    __tablename__ = "tutor_message_audio"
    __table_args__ = (
        sa.UniqueConstraint(
            "conversation_id",
            "message_index",
            "language",
            name="uq_tutor_message_audio_conv_idx_lang",
        ),
        sa.Index("ix_tutor_message_audio_conversation_id", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_index: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[str] = mapped_column(String(5), nullable=False)
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
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    conversation: Mapped[TutorConversation] = relationship(
        "TutorConversation",
        foreign_keys=[conversation_id],
    )


class TutorVoiceSession(Base):
    """Audit log of live voice-call sessions for daily-minute cap enforcement."""

    __tablename__ = "tutor_voice_sessions"
    __table_args__ = (
        sa.Index("ix_tutor_voice_sessions_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    openai_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user: Mapped[User] = relationship("User", foreign_keys=[user_id])
