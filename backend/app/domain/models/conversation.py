from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module
    from app.domain.models.user import User


class TutorConversation(Base):
    __tablename__ = "tutor_conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE")
    )
    # Working set passed to Claude. After compaction this still holds the full
    # ordered history; `compacted_through_position` marks where the summary
    # ends. Durable per-message storage lives in `tutor_messages` (#1978).
    messages: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    compacted_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Increment-only billing counter — what the daily-limit check sums (#1978).
    # Never touched by compaction.
    user_messages_sent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Increment-only display counter for the sidebar thread list (#1978). Survives
    # compaction so "17 messages" never shrinks back.
    total_messages: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # High-water mark: messages[0:compacted_through_position] are represented by
    # `compacted_context`. When building the Claude payload we slice from this
    # index forward instead of replacing the array (#1978).
    compacted_through_position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    user: Mapped[User] = relationship(back_populates="tutor_conversations")
    module: Mapped[Module] = relationship(back_populates="tutor_conversations")


class TutorMessage(Base):
    """Durable per-message store for tutor conversations (#1978).

    Compaction is non-destructive: it summarises old turns into
    ``TutorConversation.compacted_context`` for the Claude payload, but every
    message ever sent is preserved as one row here. The conversation history
    endpoint reads from this table so the user can scroll back to message #1
    even after several compaction passes.
    """

    __tablename__ = "tutor_messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tutor_conversations.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
