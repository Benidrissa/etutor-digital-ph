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
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.organization import Organization
    from app.domain.models.user import User


class QuestionBankType(enum.StrEnum):
    driving = "driving"
    exam_prep = "exam_prep"
    psychotechnic = "psychotechnic"
    general_culture = "general_culture"


class QuestionBankStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    archived = "archived"


class QuestionDifficulty(enum.StrEnum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class TestMode(enum.StrEnum):
    exam = "exam"
    training = "training"
    review = "review"


class QBankAudioStatus(enum.StrEnum):
    pending = "pending"
    generating = "generating"
    ready = "ready"
    failed = "failed"


class QuestionBank(Base):
    __tablename__ = "question_banks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_type: Mapped[QuestionBankType] = mapped_column(
        Enum(QuestionBankType, name="questionbanktype"), nullable=False
    )
    language: Mapped[str] = mapped_column(String(5), server_default="fr", default="fr")
    time_per_question_sec: Mapped[int] = mapped_column(Integer, server_default="25", default=25)
    passing_score: Mapped[float] = mapped_column(Float, server_default="80.0", default=80.0)
    status: Mapped[QuestionBankStatus] = mapped_column(
        Enum(QuestionBankStatus, name="questionbankstatus"),
        server_default="draft",
        default=QuestionBankStatus.draft,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    organization: Mapped[Organization] = relationship(foreign_keys=[organization_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    questions: Mapped[list[QBankQuestion]] = relationship(
        back_populates="question_bank", cascade="all, delete-orphan"
    )
    tests: Mapped[list[QBankTest]] = relationship(
        back_populates="question_bank", cascade="all, delete-orphan"
    )


class QBankQuestion(Base):
    __tablename__ = "qbank_questions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question_bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    image_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list] = mapped_column(JSON, nullable=False)
    correct_answer_indices: Mapped[list] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_pdf_name: Mapped[str | None] = mapped_column(String, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    difficulty: Mapped[QuestionDifficulty] = mapped_column(
        Enum(QuestionDifficulty, name="questiondifficulty"),
        server_default="medium",
        default=QuestionDifficulty.medium,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question_bank: Mapped[QuestionBank] = relationship(back_populates="questions")
    audio_files: Mapped[list[QBankQuestionAudio]] = relationship(
        back_populates="question", cascade="all, delete-orphan"
    )


class QBankQuestionAudio(Base):
    __tablename__ = "qbank_question_audio"
    __table_args__ = (
        UniqueConstraint("question_id", "language", name="uq_qbank_question_audio_lang"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qbank_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[QBankAudioStatus] = mapped_column(
        Enum(QBankAudioStatus, name="qbankaudiostatus"),
        server_default="pending",
        default=QBankAudioStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question: Mapped[QBankQuestion] = relationship(back_populates="audio_files")


class QBankTest(Base):
    __tablename__ = "qbank_tests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    question_bank_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_banks.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    mode: Mapped[TestMode] = mapped_column(
        Enum(TestMode, name="testmode"), nullable=False
    )
    question_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    time_per_question_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    show_feedback: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    filter_categories: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    filter_failed_only: Mapped[bool] = mapped_column(Boolean, server_default="false", default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    question_bank: Mapped[QuestionBank] = relationship(back_populates="tests")
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    attempts: Mapped[list[QBankTestAttempt]] = relationship(
        back_populates="test", cascade="all, delete-orphan"
    )


class QBankTestAttempt(Base):
    __tablename__ = "qbank_test_attempts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("qbank_tests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), index=True, nullable=False
    )
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    correct_answers: Mapped[int] = mapped_column(Integer, nullable=False)
    time_taken_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    category_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempt_number: Mapped[int] = mapped_column(Integer, server_default="1", default=1)

    test: Mapped[QBankTest] = relationship(back_populates="attempts")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
