"""Course quality agent models (#2215).

Four tables that together let the agent:
- run a quality sweep on a course (``CourseQualityRun``),
- record per-unit assessments with token/cost accounting
  (``UnitQualityAssessment``),
- maintain a canonical course-wide glossary as the cross-unit truth
  used to detect terminology drift (``CourseGlossaryTerm``),
- preserve every overwritten ``GeneratedContent`` payload so
  regeneration is reversible (``GeneratedContentRevision``).

The state on ``GeneratedContent`` itself (``quality_score``,
``quality_status``, ``quality_flags``, ``regeneration_attempts``,
``last_quality_run_id``, ``content_revision``) lives on that model so
the hot read path (per-unit lesson fetch) stays a single row, no joins.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.course import Course
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.models.user import User


class QualityRunStatus(enum.StrEnum):
    """Lifecycle of a course quality run."""

    queued = "queued"
    scoring = "scoring"
    regenerating = "regenerating"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class QualityRunKind(enum.StrEnum):
    full = "full"
    targeted = "targeted"
    glossary_only = "glossary_only"


class UnitQualityStatus(enum.StrEnum):
    """The eight ``GeneratedContent.quality_status`` values.

    Transitions:

    - ``pending`` → ``scoring`` → {``passing`` (≥90) | ``needs_review`` (<90) | ``failed``}
    - ``needs_review`` → ``regenerating`` → ``scoring`` (loop)
    - ``passing`` → ``scoring`` (re-scored on a new run)
    - any → ``manual_override`` when ``is_manually_edited`` flips ``true``
    - ``needs_review_final``: terminal "gave up after max attempts"
    - ``manual_override`` → ``pending`` only via explicit Unlock action
    """

    pending = "pending"
    scoring = "scoring"
    passing = "passing"
    needs_review = "needs_review"
    regenerating = "regenerating"
    needs_review_final = "needs_review_final"
    manual_override = "manual_override"
    failed = "failed"


class GlossaryConsistencyStatus(enum.StrEnum):
    consistent = "consistent"
    drift_detected = "drift_detected"
    unsourced = "unsourced"


class CourseQualityRun(Base):
    """A quality sweep over a single course.

    The partial unique index ``ux_one_active_run_per_course`` (defined
    in migration 090) makes it impossible to queue two active runs for
    the same course at once — the second ``INSERT`` raises
    ``IntegrityError``. Combined with the ``(course_id,
    idempotency_key)`` unique, double-clicks within a day are
    collapsed at the DB layer rather than relying on app-level
    serialization.
    """

    __tablename__ = "course_quality_runs"
    __table_args__ = (
        UniqueConstraint("course_id", "idempotency_key", name="uq_course_quality_run_idempotency"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    run_kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), server_default="queued")
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overall_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    units_total: Mapped[int] = mapped_column(Integer, server_default="0")
    units_passing: Mapped[int] = mapped_column(Integer, server_default="0")
    units_regenerated: Mapped[int] = mapped_column(Integer, server_default="0")
    budget_credits: Mapped[int] = mapped_column(Integer, server_default="0")
    spent_credits: Mapped[int] = mapped_column(Integer, server_default="0")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    course: Mapped[Course] = relationship()
    triggered_by: Mapped[User | None] = relationship(foreign_keys=[triggered_by_user_id])
    assessments: Mapped[list[UnitQualityAssessment]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class UnitQualityAssessment(Base):
    """One scoring of one unit (one row per attempt).

    Tokens/cost are recorded so we can prove the prompt-cache savings
    after rollout (``cache_read_tokens`` should dominate from the
    second unit onward in a course run).
    """

    __tablename__ = "unit_quality_assessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("course_quality_runs.id", ondelete="CASCADE"), index=True
    )
    generated_content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generated_content.id", ondelete="CASCADE")
    )
    attempt_number: Mapped[int] = mapped_column(SmallInteger, server_default="1")
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    dimension_scores: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    flags: Mapped[list] = mapped_column(JSONB, server_default="[]")
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    credit_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    run: Mapped[CourseQualityRun] = relationship(back_populates="assessments")


class CourseGlossaryTerm(Base):
    """Canonical term + definition per (course, language).

    The agent compares unit content against this table to flag
    terminology drift (the bug from #2215 — same term, different
    definition across units). When the glossary pre-pass detects
    divergent definitions across modules, ``consistency_status`` flips
    to ``drift_detected`` and ``drift_details`` carries the
    explanation.
    """

    __tablename__ = "course_glossary_terms"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "term_normalized",
            "language",
            name="uq_glossary_course_term_lang",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    term_normalized: Mapped[str] = mapped_column(String(160))
    term_display: Mapped[str] = mapped_column(String(160))
    language: Mapped[str] = mapped_column(String(2))
    canonical_definition: Mapped[str] = mapped_column(Text)
    first_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("module_units.id", ondelete="SET NULL"), nullable=True
    )
    occurrences: Mapped[list] = mapped_column(JSONB, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), server_default="auto")
    consistency_status: Mapped[str] = mapped_column(String(24), server_default="consistent")
    drift_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_citations: Mapped[list] = mapped_column(JSONB, server_default="[]")
    alt_phrasings: Mapped[list] = mapped_column(JSONB, server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    course: Mapped[Course] = relationship()
    first_unit: Mapped[ModuleUnit | None] = relationship(foreign_keys=[first_unit_id])


class GeneratedContentRevision(Base):
    """Pre-image of ``GeneratedContent`` before each overwrite.

    Today ``force_regenerate=True`` overwrites in place; once this
    table exists the regenerator first dumps the prior payload here
    (with ``trigger`` indicating who/why) and only then writes the new
    content. Lets us roll back a regression without touching git.
    """

    __tablename__ = "generated_content_revisions"
    __table_args__ = (
        UniqueConstraint("generated_content_id", "revision", name="uq_genc_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    generated_content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("generated_content.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(SmallInteger)
    content: Mapped[dict] = mapped_column(JSONB)
    sources_cited: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quality_score_before: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    quality_flags_before: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    trigger: Mapped[str] = mapped_column(String(32))
    triggered_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
