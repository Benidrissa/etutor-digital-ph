from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.user import User


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    quiz_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_content.id"), index=True)
    answers: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float | None]
    time_taken_sec: Mapped[int | None] = mapped_column(Integer)
    attempted_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="quiz_attempts")
    quiz: Mapped[GeneratedContent] = relationship(back_populates="quiz_attempts")
