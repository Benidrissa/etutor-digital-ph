from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.user import User


class LessonReading(Base):
    __tablename__ = "lesson_readings"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_content.id"), index=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, server_default="0")
    completion_percentage: Mapped[float] = mapped_column(server_default="0.0")
    read_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="lesson_readings")
    lesson: Mapped[GeneratedContent] = relationship()
