from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.module import Module
    from app.domain.models.user import User


class UserModuleProgress(Base):
    __tablename__ = "user_module_progress"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String, server_default="locked")
    completion_pct: Mapped[float] = mapped_column(server_default="0.0")
    quiz_score_avg: Mapped[float | None]
    time_spent_minutes: Mapped[int] = mapped_column(server_default="0")
    last_accessed: Mapped[datetime | None]

    user: Mapped[User] = relationship(back_populates="module_progress")
    module: Mapped[Module] = relationship(back_populates="user_progress")
