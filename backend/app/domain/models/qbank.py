"""Question bank models — banks, questions, and attempt tracking."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.organization import Organization
    from app.domain.models.user import User


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    pass_score: Mapped[float] = mapped_column(Float, default=70.0)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(foreign_keys=[organization_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    questions: Mapped[list[Question]] = relationship(
        back_populates="bank", cascade="all, delete-orphan"
    )
    attempts: Mapped[list[QBankAttempt]] = relationship(
        back_populates="bank", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "qbank_questions"
    __table_args__ = (Index("ix_qbank_questions_bank_id", "bank_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[dict] = mapped_column(JSON, nullable=False)
    correct_option: Mapped[str] = mapped_column(String(10), nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    bank: Mapped[QuestionBank] = relationship(back_populates="questions")


class QBankAttempt(Base):
    __tablename__ = "qbank_attempts"
    __table_args__ = (
        Index("ix_qbank_attempts_bank_id", "bank_id"),
        Index("ix_qbank_attempts_user_id", "user_id"),
        Index("ix_qbank_attempts_bank_user", "bank_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False)
    time_taken_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    bank: Mapped[QuestionBank] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
