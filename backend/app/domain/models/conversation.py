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
    module_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("modules.id"))
    messages: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    compacted_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    compacted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    user: Mapped[User] = relationship(back_populates="tutor_conversations")
    module: Mapped[Module] = relationship(back_populates="tutor_conversations")
