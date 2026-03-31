from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.auth import MagicLink, RefreshToken, TOTPSecret
    from app.domain.models.conversation import TutorConversation
    from app.domain.models.flashcard import FlashcardReview
    from app.domain.models.lesson_reading import LessonReading
    from app.domain.models.progress import UserModuleProgress
    from app.domain.models.quiz import PlacementTestAttempt, QuizAttempt, SummativeAssessmentAttempt


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    preferred_language: Mapped[str] = mapped_column(String(2), server_default="fr")
    country: Mapped[str | None] = mapped_column(String)
    professional_role: Mapped[str | None] = mapped_column(String)
    current_level: Mapped[int] = mapped_column(server_default="1")
    streak_days: Mapped[int] = mapped_column(server_default="0")
<<<<<<< HEAD
    last_active: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
=======
    avatar_url: Mapped[str | None] = mapped_column(String)
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
>>>>>>> 0c8526b (feat(profile): implement user profile page with view and edit functionality)

    # Auth relationships
    totp_secret: Mapped[TOTPSecret | None] = relationship(back_populates="user")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    magic_links: Mapped[list[MagicLink]] = relationship(back_populates="user")

    # Learning relationships
    module_progress: Mapped[list[UserModuleProgress]] = relationship(back_populates="user")
    quiz_attempts: Mapped[list[QuizAttempt]] = relationship(back_populates="user")
    summative_attempts: Mapped[list[SummativeAssessmentAttempt]] = relationship(
        back_populates="user"
    )
    placement_attempts: Mapped[list[PlacementTestAttempt]] = relationship(back_populates="user")
    flashcard_reviews: Mapped[list[FlashcardReview]] = relationship(back_populates="user")
    lesson_readings: Mapped[list[LessonReading]] = relationship(back_populates="user")
    tutor_conversations: Mapped[list[TutorConversation]] = relationship(back_populates="user")
