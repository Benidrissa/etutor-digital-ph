"""Pydantic schemas for the course quality agent (#2215).

Two roles:

1. **Structured-output contracts for the LLM auditor.** ``UnitQualityReport``
   and ``CourseGlossaryDocument`` are the schemas Claude returns
   directly via ``ClaudeService.generate_structured_content_cached``.
   Keeping them strict catches malformed JSON at the parse boundary
   instead of letting bad data into the DB.

2. **API response shapes for admin endpoints.** ``CourseQualityRunSummary``,
   ``GlossaryEntryResponse``, etc. are read-only DTOs returned by
   ``admin_courses.py`` to the admin UI.

The two roles share schemas where they overlap (a glossary entry is the
same shape coming from the LLM as it is going out the API), to avoid
double-defining structures.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

# ---- enums (string-typed for forward compatibility w/ DB columns) ----

QualityStatus = Literal[
    "pending",
    "scoring",
    "passing",
    "needs_review",
    "regenerating",
    "needs_review_final",
    "manual_override",
    "failed",
]

RunStatus = Literal["queued", "scoring", "regenerating", "completed", "failed", "cancelled"]

RunKind = Literal["full", "targeted", "glossary_only"]


FlagCategory = Literal[
    "terminology_drift",
    "ungrounded_claim",
    "syllabus_scope_drift",
    "internal_contradiction",
    "pedagogical_mismatch",
    "structural_gap",
]

Severity = Literal["low", "medium", "high", "blocking"]


# ---- LLM structured-output schemas ----


class QualityFlag(BaseModel):
    """One specific issue surfaced by the auditor.

    ``location`` is a JSONPath into ``GeneratedContent.content`` (e.g.
    ``concepts[2]`` or ``synthesis``) so the admin UI can highlight
    the offending span without an extra round-trip to the LLM.
    ``evidence_unit_id`` references the *other* unit when the flag is
    cross-unit (e.g. terminology drift between 1.1 and 2.3).
    """

    category: FlagCategory
    severity: Severity
    location: str = Field(..., description="JSONPath into GeneratedContent.content")
    description: str = Field(..., description="What is wrong")
    evidence: str = Field(..., description="Quoted text from the unit")
    suggested_fix: str = Field(..., description="Actionable fix paste-able as a constraint")
    evidence_unit_id: str | None = Field(
        None, description="When cross-unit, the unit_number this flag points at"
    )


class DimensionScores(BaseModel):
    """Per-dimension scores; weighted to produce ``UnitQualityReport.score``.

    Weights live in the auditor prompt, not in code, so admins can
    tune them via platform settings without a deploy.
    """

    terminology_consistency: int = Field(..., ge=0, le=100)
    source_grounding: int = Field(..., ge=0, le=100)
    syllabus_alignment: int = Field(..., ge=0, le=100)
    internal_contradictions: int = Field(..., ge=0, le=100)
    pedagogical_fit: int = Field(..., ge=0, le=100)
    structural_completeness: int = Field(..., ge=0, le=100)


class UnitQualityReport(BaseModel):
    """The auditor's verdict on a single unit (one LLM call → one of these).

    ``regeneration_constraints`` is the hand-off to the regenerator —
    one imperative sentence per constraint, naming both the problem
    and the fix (see prompts/quality.py for examples).
    """

    quality_score: int = Field(..., ge=0, le=100)
    dimension_scores: DimensionScores
    flags: list[QualityFlag] = Field(default_factory=list)
    needs_regeneration: bool
    regeneration_constraints: list[str] = Field(default_factory=list)


class GlossaryEntry(BaseModel):
    """One canonical term in the course glossary.

    Lives both as the LLM's structured output (during glossary
    extraction) and as the row shape persisted to
    ``course_glossary_terms``.
    """

    term: str = Field(..., description="Canonical surface form, lowercase")
    canonical_definition: str = Field(..., description="1–2 sentences, source-grounded")
    first_appears_in_unit: str = Field(..., description="unit_number like '1.1'")
    alt_phrasings: list[str] = Field(default_factory=list)
    source_citations: list[str] = Field(default_factory=list)
    consistency_status: Literal["consistent", "drift_detected", "unsourced"] = "consistent"
    drift_details: str | None = None


class CourseGlossaryDocument(BaseModel):
    """Top-level structured output from the glossary pre-pass."""

    entries: list[GlossaryEntry] = Field(default_factory=list)


# ---- API response DTOs (admin endpoints) ----


class GlossaryEntryResponse(BaseModel):
    """Glossary term as returned by the admin glossary endpoint."""

    id: uuid.UUID
    term_display: str
    language: str
    canonical_definition: str
    first_unit_number: str | None = None
    consistency_status: str
    drift_details: str | None = None
    occurrences_count: int = 0
    status: str

    model_config = {"from_attributes": True}


class UnitQualitySummary(BaseModel):
    """Per-unit roll-up for the run-detail view."""

    generated_content_id: uuid.UUID
    unit_number: str | None
    content_type: str
    language: str
    quality_score: float | None
    quality_status: QualityStatus
    flag_count: int
    regeneration_attempts: int
    is_manually_edited: bool
    last_assessed_at: datetime | None


class CourseQualityRunSummary(BaseModel):
    """Run-level summary for the dashboard."""

    id: uuid.UUID
    course_id: uuid.UUID
    run_kind: RunKind
    status: RunStatus
    started_at: datetime | None
    finished_at: datetime | None
    overall_score: float | None
    units_total: int
    units_passing: int
    units_regenerated: int
    budget_credits: int
    spent_credits: int
    triggered_by_user_id: uuid.UUID | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class CourseQualityRunDetail(CourseQualityRunSummary):
    """Run summary plus the per-unit breakdown."""

    units: list[UnitQualitySummary] = Field(default_factory=list)


class UnitQualityDetail(BaseModel):
    """Per-unit detail with full flags + dimension scores for the drill-in view.

    Combines hot fields from ``GeneratedContent`` (state, flags) with
    the latest ``UnitQualityAssessment`` row's dimension scores so the
    UI can render the radar/bar chart without a second round-trip.
    """

    generated_content_id: uuid.UUID
    unit_number: str | None
    content_type: str
    language: str
    quality_score: float | None
    quality_status: QualityStatus
    flag_count: int
    regeneration_attempts: int
    is_manually_edited: bool
    validated: bool
    quality_assessed_at: datetime | None
    last_quality_run_id: uuid.UUID | None
    quality_flags: list[QualityFlag] = Field(default_factory=list)
    dimension_scores: DimensionScores | None = None
    latest_attempt_id: uuid.UUID | None = None
    latest_attempt_number: int | None = None
    latest_attempt_score: float | None = None


class ReviewQueueEntry(BaseModel):
    """One row in the cross-course review queue.

    Sorted server-side by ``(units_needs_review_final + units_failed)``
    desc, then ``units_needs_review`` desc, then ``glossary_drift_count``
    desc — courses needing attention first.
    """

    course_id: uuid.UUID
    course_title_fr: str
    course_title_en: str
    owner_id: uuid.UUID | None
    units_total: int
    units_passing: int
    units_needs_review: int
    units_needs_review_final: int
    units_failed: int
    glossary_drift_count: int
    last_assessed_at: datetime | None
    last_run: CourseQualityRunSummary | None = None


class RunQualityCheckRequest(BaseModel):
    """Request body for ``POST /admin/courses/{id}/quality/runs``."""

    run_kind: RunKind = "full"
    force: bool = Field(
        False,
        description="Bypass the same-day idempotency-key collapse and start a fresh run.",
    )
    budget_credits: int | None = Field(
        None,
        ge=0,
        description="Override the default per-run budget. Defaults: 200 for full, 50 for targeted.",
    )


class RegenerateUnitRequest(BaseModel):
    """Request body for the targeted unit regeneration endpoint."""

    constraints: list[str] | None = Field(
        None,
        description=(
            "Override the auto-derived constraints from the latest "
            "assessment. Useful when the admin wants to fix something "
            "the LLM missed."
        ),
    )


class ResolveUnitRequest(BaseModel):
    """Mark a flagged unit as resolved without regenerating."""

    note: str | None = None


def to_decimal_safe(value: Decimal | float | int | None) -> float | None:
    """Coerce DB Decimal scores to float for JSON responses."""
    if value is None:
        return None
    return float(value)
