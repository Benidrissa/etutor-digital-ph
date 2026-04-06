from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base


class UserRole(enum.StrEnum):
    user = "user"
    expert = "expert"
    admin = "admin"


if TYPE_CHECKING:
    from app.domain.models.auth import (
        EmailOTP,
        MagicLink,
        PasswordResetToken,
        RefreshToken,
        TOTPSecret,
    )
    from app.domain.models.conversation import TutorConversation
    from app.domain.models.credit import CreditAccount
    from app.domain.models.flashcard import FlashcardReview
    from app.domain.models.learner_memory import LearnerMemory
    from app.domain.models.lesson_reading import LessonReading
    from app.domain.models.progress import UserModuleProgress
    from app.domain.models.quiz import PlacementTestAttempt, QuizAttempt, SummativeAssessmentAttempt
    from app.domain.models.subscription import Subscription, SubscriptionPayment


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone_number IS NOT NULL",
            name="ck_users_email_or_phone",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String)
    preferred_language: Mapped[str] = mapped_column(String(2), server_default="fr")
    country: Mapped[str | None] = mapped_column(String)
    professional_role: Mapped[str | None] = mapped_column(String)
    current_level: Mapped[int] = mapped_column(server_default="1")
    streak_days: Mapped[int] = mapped_column(server_default="0")
    avatar_url: Mapped[str | None] = mapped_column(String)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), server_default="user", default=UserRole.user
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    analytics_opt_out: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failed_password_attempts: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    password_locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Auth relationships
    totp_secret: Mapped[TOTPSecret | None] = relationship(back_populates="user")
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user")
    magic_links: Mapped[list[MagicLink]] = relationship(back_populates="user")
    email_otps: Mapped[list[EmailOTP]] = relationship(back_populates="user")
    password_reset_tokens: Mapped[list[PasswordResetToken]] = relationship(back_populates="user")

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
    learner_memory: Mapped[LearnerMemory | None] = relationship(
        back_populates="user", uselist=False
    )
    credit_account: Mapped[CreditAccount | None] = relationship(
        back_populates="user", uselist=False
    )
    subscription: Mapped[Subscription | None] = relationship(back_populates="user", uselist=False)
    subscription_payments: Mapped[list[SubscriptionPayment]] = relationship(back_populates="user")
