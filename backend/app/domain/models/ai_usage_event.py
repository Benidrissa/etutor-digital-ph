"""Per-call AI usage ledger (#2629).

One row per provider API call (or per batched embedding call — see
``request_count``), recording who/what/why and the computed cost so the admin
analytics page can attribute spend per user/model/provider/feature. Display-only
in this phase: rows never debit credits; a future ``generation_cost`` credit
writer can reference ``ai_usage_events.id`` from ``credit_transactions.metadata_json``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

# Operation kinds (what the API call was)
OP_CHAT = "chat"
OP_EMBEDDING = "embedding"
OP_IMAGE = "image"
OP_TTS = "tts"
OP_STT = "stt"
OP_REALTIME = "realtime"

# Feature taxonomy (why the call happened). Plain strings, not a PG enum —
# adding a feature must never require a migration.
FEATURE_RAG_INDEXING = "rag_indexing"
FEATURE_RAG_QUERY = "rag_query"
FEATURE_LESSON_GENERATION = "lesson_generation"
FEATURE_QUIZ_GENERATION = "quiz_generation"
FEATURE_FLASHCARD_GENERATION = "flashcard_generation"
FEATURE_CASE_STUDY = "case_study"
FEATURE_SYLLABUS_SUMMARY = "syllabus_summary"
FEATURE_SYLLABUS_GENERATION = "syllabus_generation"
FEATURE_COURSE_STRUCTURE = "course_structure"
FEATURE_PREASSESSMENT = "preassessment"
FEATURE_TUTOR_CHAT = "tutor_chat"
FEATURE_TUTOR_TTS = "tutor_tts"
FEATURE_LESSON_AUDIO = "lesson_audio"
FEATURE_QBANK_AUDIO = "qbank_audio"
FEATURE_TRANSCRIPTION = "transcription"
FEATURE_VOICE_SESSION = "voice_session"
FEATURE_QUALITY_AGENT = "quality_agent"
FEATURE_IMAGE_GENERATION = "image_generation"
FEATURE_IMAGE_METADATA = "image_metadata"
FEATURE_TRANSLATION = "translation"
FEATURE_UNKNOWN = "unknown"


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (
        Index("ix_ai_usage_events_created", "created_at"),
        Index("ix_ai_usage_events_feature_created", "feature", "created_at"),
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
        Index("ix_ai_usage_events_provider_created", "provider", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(20), nullable=False)
    feature: Mapped[str] = mapped_column(String(50), nullable=False, default=FEATURE_UNKNOWN)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="SET NULL"), nullable=True
    )
    api_key_source: Mapped[str] = mapped_column(String(10), nullable=False, default="platform")
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    images_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    characters: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # A batched embedding run collapses N API calls into 1 row; this keeps the call count.
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Fractional cents — integer cents would round every embedding/TTS call to 0.
    cost_cents: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    cost_estimated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
