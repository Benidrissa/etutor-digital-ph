"""Question bank domain models — banks, questions, tests, and attempts."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.organization import Organization
    from app.domain.models.user import User


class BankType(enum.StrEnum):
    exam = "exam"
    training = "training"
    mixed = "mixed"


class TestMode(enum.StrEnum):
    exam = "exam"
    training = "training"
    review = "review"


class QuestionBank(Base):
    __tablename__ = "question_banks"
    __table_args__ = (
        Index("ix_qbanks_org_id", "organization_id"),
        Index("ix_qbanks_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_type: Mapped[BankType] = mapped_column(
        Enum(BankType, name="banktype"), nullable=False, default=BankType.mixed
    )
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
    questions: Mapped[list[BankQuestion]] = relationship(
        back_populates="bank", cascade="all, delete-orphan"
    )
    tests: Mapped[list[BankTest]] = relationship(
        back_populates="bank", cascade="all, delete-orphan"
    )


class BankQuestion(Base):
    __tablename__ = "bank_questions"
    __table_args__ = (
        Index("ix_bquestions_bank_id", "bank_id"),
        Index("ix_bquestions_category", "category"),
        Index("ix_bquestions_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSONB, nullable=False)
    correct_answer: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(20), server_default="medium", default="medium")
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    bank: Mapped[QuestionBank] = relationship(back_populates="questions")


class BankTest(Base):
    __tablename__ = "bank_tests"
    __table_args__ = (
        Index("ix_btests_bank_id", "bank_id"),
        Index("ix_btests_is_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[TestMode] = mapped_column(
        Enum(TestMode, name="testmode"), nullable=False, default=TestMode.exam
    )
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passing_score: Mapped[float] = mapped_column(Float, nullable=False, default=70.0)
    category_filter: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty_filter: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    show_answers: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    bank: Mapped[QuestionBank] = relationship(back_populates="tests")
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    attempts: Mapped[list[TestAttempt]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )


class TestAttempt(Base):
    __tablename__ = "test_attempts"
    __table_args__ = (
        Index("ix_tattempts_test_id", "test_id"),
        Index("ix_tattempts_user_id", "user_id"),
        Index("ix_tattempts_test_user", "test_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_tests.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    answers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    question_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    category_breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    time_taken_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    test: Mapped[BankTest] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
