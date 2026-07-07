"""Unit tests for the course quality agent (#2215).

Pure-function tests only — no DB, no Anthropic. The end-to-end
integration tests live separately and require a real PostgreSQL +
Anthropic API key.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ai.prompts.quality import (
    DIMENSION_WEIGHTS,
    build_auditor_user_message,
    build_cached_system_blocks,
    compute_weighted_score,
    constraints_block_from_report,
    has_critical_floor_violation,
)
from app.api.v1.schemas.quality import (
    DimensionScores,
    GlossaryEntry,
    QualityFlag,
    UnitQualityReport,
)
from app.domain.services.quality_agent_service import (
    DEFAULT_BUDGET_FULL,
    DEFAULT_BUDGET_TARGETED,
    MAX_REGEN_ATTEMPTS,
    MIN_IMPROVEMENT_PER_ATTEMPT,
    PASSING_SCORE_THRESHOLD,
    calculate_cost_cents,
    normalize_term,
)

# ---- Rubric weights ---------------------------------------------------


def test_dimension_weights_sum_to_100():
    assert sum(DIMENSION_WEIGHTS.values()) == 100


def test_compute_weighted_score_perfect():
    perfect = {dim: 100 for dim in DIMENSION_WEIGHTS}
    assert compute_weighted_score(perfect) == 100


def test_compute_weighted_score_zero():
    zero = {dim: 0 for dim in DIMENSION_WEIGHTS}
    assert compute_weighted_score(zero) == 0


def test_compute_weighted_score_uniform_72():
    """Uniform 72 → weighted average of 72."""
    seventy_two = {dim: 72 for dim in DIMENSION_WEIGHTS}
    assert compute_weighted_score(seventy_two) == 72


def test_compute_weighted_score_clamps_out_of_range():
    """Scores above 100 / below 0 must be clamped before weighting."""
    # All over 100 → 100. All negative → 0.
    over = {dim: 200 for dim in DIMENSION_WEIGHTS}
    assert compute_weighted_score(over) == 100
    under = {dim: -50 for dim in DIMENSION_WEIGHTS}
    assert compute_weighted_score(under) == 0


def test_compute_weighted_score_uneven():
    """Verify the weighting actually weights — terminology (25) dominates."""
    # All others 100, terminology 0 → 100*0.25 = ... wait, 100 * 0.75 = 75.
    scores = {
        "terminology_consistency": 0,
        "source_grounding": 100,
        "syllabus_alignment": 100,
        "internal_contradictions": 100,
        "pedagogical_fit": 100,
        "structural_completeness": 100,
    }
    expected = round(0 * 25 / 100 + 100 * 75 / 100)
    assert compute_weighted_score(scores) == expected
    assert compute_weighted_score(scores) == 75


def test_compute_weighted_score_missing_dimension_treated_as_zero():
    """Missing dim should contribute 0 (defensive)."""
    partial = {"terminology_consistency": 100}
    assert compute_weighted_score(partial) == 25


# ---- Critical-floor rule ---------------------------------------------


def test_floor_rule_terminology_below_70():
    scores = {
        "terminology_consistency": 60,
        "source_grounding": 100,
        "internal_contradictions": 100,
        "pedagogical_fit": 100,
        "syllabus_alignment": 100,
        "structural_completeness": 100,
    }
    assert has_critical_floor_violation(scores) is True


def test_floor_rule_grounding_below_70():
    scores = {
        "terminology_consistency": 100,
        "source_grounding": 50,
        "internal_contradictions": 100,
        "pedagogical_fit": 100,
        "syllabus_alignment": 100,
        "structural_completeness": 100,
    }
    assert has_critical_floor_violation(scores) is True


def test_floor_rule_contradictions_below_70():
    scores = {
        "terminology_consistency": 100,
        "source_grounding": 100,
        "internal_contradictions": 65,
        "pedagogical_fit": 100,
        "syllabus_alignment": 100,
        "structural_completeness": 100,
    }
    assert has_critical_floor_violation(scores) is True


def test_floor_rule_non_critical_dim_low_does_not_trip():
    """Pedagogical fit at 0 should NOT trip floor (it's not a critical dim)."""
    scores = {
        "terminology_consistency": 100,
        "source_grounding": 100,
        "internal_contradictions": 100,
        "pedagogical_fit": 0,
        "syllabus_alignment": 100,
        "structural_completeness": 100,
    }
    assert has_critical_floor_violation(scores) is False


# ---- normalize_term --------------------------------------------------


def test_normalize_term_lowercases_and_strips():
    assert normalize_term("  ECART-Type ") == "ecart-type"


def test_normalize_term_strips_accents():
    """Same canonical form for 'Écart-type' and 'ecart-type'."""
    assert normalize_term("Écart-type") == normalize_term("ecart-type")


def test_normalize_term_collapses_internal_whitespace():
    assert normalize_term("écart  type") == normalize_term("ecart type")


def test_normalize_term_empty():
    assert normalize_term("") == ""
    assert normalize_term("   ") == ""


# ---- Cost calculation -----------------------------------------------


def test_cost_calculation_no_cache():
    """100k input + 10k output, no caching."""
    cents = calculate_cost_cents(
        {
            "input_tokens": 100_000,
            "output_tokens": 10_000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )
    # 100k * 300 / 1M = 30 ; 10k * 1500 / 1M = 15. Total = 45 cents.
    assert cents == 45


def test_cost_calculation_cache_dominant():
    """When the prefix is cached, cost should drop dramatically."""
    no_cache = calculate_cost_cents(
        {
            "input_tokens": 25_000,
            "output_tokens": 1_000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    )
    with_cache = calculate_cost_cents(
        {
            "input_tokens": 0,
            "output_tokens": 1_000,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 25_000,
        }
    )
    # Cache reads should be roughly 10% of input cost.
    assert with_cache < no_cache
    assert with_cache <= no_cache // 4  # Substantial savings


def test_cost_calculation_handles_none():
    """All None usage values shouldn't crash."""
    cents = calculate_cost_cents(
        {
            "input_tokens": None,
            "output_tokens": None,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": None,
        }
    )
    assert cents == 0


# ---- Constraint block formatting ------------------------------------


def test_constraints_block_empty_returns_empty_string():
    assert constraints_block_from_report([]) == ""
    assert constraints_block_from_report(["   ", ""]) != ""  # has at least header


def test_constraints_block_renders_bullets():
    block = constraints_block_from_report(["Use term X.", "Cite page Y."])
    assert "## ADDITIONAL CONSTRAINTS" in block
    assert "- Use term X." in block
    assert "- Cite page Y." in block


def test_constraints_block_filters_blank_bullets():
    block = constraints_block_from_report(["Real one.", "", "  ", "Another."])
    assert "Real one." in block
    assert "Another." in block
    # No empty bullet lines like "- " should appear.
    assert "- \n" not in block.replace("- Real one.\n- Another.\n", "")


# ---- Pydantic schemas -----------------------------------------------


def test_unit_quality_report_validates_well_formed_json():
    payload = {
        "quality_score": 88,
        "dimension_scores": {
            "terminology_consistency": 80,
            "source_grounding": 90,
            "syllabus_alignment": 95,
            "internal_contradictions": 85,
            "pedagogical_fit": 90,
            "structural_completeness": 90,
        },
        "flags": [
            {
                "category": "terminology_drift",
                "severity": "high",
                "location": "concepts[1]",
                "description": "Term defined differently than unit 1.1",
                "evidence": "...",
                "suggested_fix": "Use the canonical definition.",
                "evidence_unit_id": "1.1",
            }
        ],
        "needs_regeneration": True,
        "regeneration_constraints": ["Use canonical definition for term X."],
    }
    report = UnitQualityReport.model_validate(payload)
    assert report.quality_score == 88
    assert len(report.flags) == 1
    assert report.flags[0].evidence_unit_id == "1.1"


def test_unit_quality_report_rejects_score_above_100():
    bad = {
        "quality_score": 101,
        "dimension_scores": {
            "terminology_consistency": 100,
            "source_grounding": 100,
            "syllabus_alignment": 100,
            "internal_contradictions": 100,
            "pedagogical_fit": 100,
            "structural_completeness": 100,
        },
        "flags": [],
        "needs_regeneration": False,
        "regeneration_constraints": [],
    }
    with pytest.raises(ValidationError):
        UnitQualityReport.model_validate(bad)


def test_glossary_entry_default_consistency_status():
    entry = GlossaryEntry(
        term="standard deviation",
        canonical_definition="Square root of variance.",
        first_appears_in_unit="1.1",
    )
    assert entry.consistency_status == "consistent"
    assert entry.alt_phrasings == []


def test_quality_flag_rejects_invalid_category():
    with pytest.raises(ValidationError):
        QualityFlag.model_validate(
            {
                "category": "made_up_category",
                "severity": "high",
                "location": "x",
                "description": "y",
                "evidence": "z",
                "suggested_fix": "fix",
            }
        )


# ---- Cached system blocks layout -----------------------------------


def test_cached_system_blocks_has_4_breakpoints():
    blocks = build_cached_system_blocks(
        syllabus_block="syllabus content",
        source_summaries_block="summary content",
        glossary_block="[]",
    )
    assert len(blocks) == 4
    for b in blocks:
        assert b["type"] == "text"
        assert b.get("cache_control") == {"type": "ephemeral"}


def test_cached_system_blocks_includes_payloads():
    blocks = build_cached_system_blocks(
        syllabus_block="MY_SYLLABUS",
        source_summaries_block="MY_SUMMARIES",
        glossary_block="MY_GLOSSARY",
    )
    full = "\n".join(b["text"] for b in blocks)
    assert "MY_SYLLABUS" in full
    assert "MY_SUMMARIES" in full
    assert "MY_GLOSSARY" in full
    # Auditor system text always there.
    assert "Course Quality Auditor" in full


# ---- Auditor user message --------------------------------------------


def test_auditor_user_message_contains_unit_payload():
    msg = build_auditor_user_message(
        unit_number="1.2",
        unit_title="Hypothesis Testing",
        content_type="lesson",
        language="en",
        level=2,
        unit_content={"introduction": "intro text", "concepts": []},
        sources_cited=["src:p1"],
        neighbor_digest=[{"unit_number": "1.1", "title": "Intro", "summary": "summary 1"}],
        rag_excerpts=[{"source": "triola", "chapter": "5", "page": "47", "content": "chunk"}],
    )
    assert "1.2" in msg
    assert "Hypothesis Testing" in msg
    assert "intro text" in msg
    # neighbor digest present
    assert "1.1" in msg
    # rag excerpt present
    assert "triola" in msg


# ---- Service constants -----------------------------------------------


def test_threshold_and_caps_sane():
    """Sanity-check the public knobs match the plan."""
    assert PASSING_SCORE_THRESHOLD == 90
    assert MAX_REGEN_ATTEMPTS == 2
    assert MIN_IMPROVEMENT_PER_ATTEMPT == 3
    assert DEFAULT_BUDGET_FULL == 200
    assert DEFAULT_BUDGET_TARGETED == 50


# ---- Anti-oscillation guard logic (pure decision function) ----------


def _should_stop_loop(
    *,
    is_manually_edited: bool,
    needs_regen: bool,
    current_score: int,
    prev_score: int | None,
    attempts: int,
) -> bool:
    """Mirror of the conditions inside assess_and_regenerate_loop.

    Reimplemented here as a pure function so we can unit-test the
    decision tree without running Celery + Anthropic. The real loop
    in CourseQualityService keeps the same logic; if you change one,
    change both.
    """
    if is_manually_edited:
        return True
    if not needs_regen and current_score >= PASSING_SCORE_THRESHOLD:
        return True
    if attempts >= MAX_REGEN_ATTEMPTS:
        return True
    return prev_score is not None and current_score - prev_score < MIN_IMPROVEMENT_PER_ATTEMPT


def test_loop_stops_when_passing():
    assert (
        _should_stop_loop(
            is_manually_edited=False,
            needs_regen=False,
            current_score=92,
            prev_score=None,
            attempts=0,
        )
        is True
    )


def test_loop_continues_when_failing_first_attempt():
    assert (
        _should_stop_loop(
            is_manually_edited=False,
            needs_regen=True,
            current_score=72,
            prev_score=None,
            attempts=0,
        )
        is False
    )


def test_loop_stops_at_max_attempts():
    assert (
        _should_stop_loop(
            is_manually_edited=False,
            needs_regen=True,
            current_score=72,
            prev_score=70,
            attempts=MAX_REGEN_ATTEMPTS,
        )
        is True
    )


def test_loop_stops_on_oscillation_88_to_90_to_88():
    """88 → 90 (pass), but if it had been 88 → 90 → 88 we'd stop on the third."""
    # 88 first attempt, 90 second — passes the +3 guard? +2 is below +3, so stop.
    assert (
        _should_stop_loop(
            is_manually_edited=False,
            needs_regen=True,
            current_score=90,
            prev_score=88,
            attempts=1,
        )
        is True
    )


def test_loop_continues_when_improving_well():
    """50 → 75 (+25) is healthy improvement; keep going."""
    assert (
        _should_stop_loop(
            is_manually_edited=False,
            needs_regen=True,
            current_score=75,
            prev_score=50,
            attempts=1,
        )
        is False
    )


def test_loop_stops_immediately_when_locked():
    """Manually edited content always stops, even if score would warrant retry."""
    assert (
        _should_stop_loop(
            is_manually_edited=True,
            needs_regen=True,
            current_score=10,
            prev_score=None,
            attempts=0,
        )
        is True
    )


# ---- DimensionScores Pydantic ---------------------------------------


def test_dimension_scores_round_trip():
    scores = DimensionScores(
        terminology_consistency=80,
        source_grounding=85,
        syllabus_alignment=90,
        internal_contradictions=85,
        pedagogical_fit=80,
        structural_completeness=90,
    )
    payload = scores.model_dump()
    rebuilt = DimensionScores.model_validate(payload)
    assert rebuilt == scores


def test_dimension_scores_rejects_negative():
    with pytest.raises(ValidationError):
        DimensionScores(
            terminology_consistency=-1,
            source_grounding=80,
            syllabus_alignment=80,
            internal_contradictions=80,
            pedagogical_fit=80,
            structural_completeness=80,
        )


# ---- build_quality_context eager-loads first_unit (greenlet regression) ----


async def test_build_quality_context_eager_loads_glossary_first_unit():
    """Regression: the glossary loop reads ``t.first_unit.unit_number``. On an
    AsyncSession a lazy relationship access raises ``greenlet_spawn has not
    been called``, failing the whole assess_course_task sweep. The query must
    eager-load ``first_unit`` via selectinload.
    """
    import uuid
    from unittest.mock import AsyncMock, MagicMock

    from app.domain.models.course import Course
    from app.domain.models.course_quality import CourseGlossaryTerm
    from app.domain.services.quality_agent_service import CourseQualityService

    captured: list = []

    course = MagicMock()
    course.syllabus_context = None
    course.syllabus_json = None
    course.objectives_json = None

    def _result_for(stmt):
        captured.append(stmt)
        result = MagicMock()
        entity = stmt.column_descriptions[0]["entity"]
        if entity is Course:
            result.scalar_one_or_none.return_value = course
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_result_for)

    service = CourseQualityService(MagicMock(), MagicMock())
    await service.build_quality_context(course_id=uuid.uuid4(), language="fr", session=session)

    gloss_stmts = [s for s in captured if s.column_descriptions[0]["entity"] is CourseGlossaryTerm]
    assert gloss_stmts, "glossary query was not executed"
    option_paths = " ".join(str(o.path) for o in gloss_stmts[0]._with_options)
    assert "first_unit" in option_paths, (
        "glossary query must selectinload(CourseGlossaryTerm.first_unit) to "
        "avoid a lazy-load greenlet error in the Celery sweep"
    )


# ---- Auto post-generation QA: run_id is optional (#2456) --------------


def test_unit_quality_assessment_run_id_is_nullable():
    """Auto post-generation QA persists a per-unit score with no course run.

    The whole task/service layer already treats run_id as optional, so the
    column must be nullable — otherwise every auto-QA insert hits a NOT NULL
    violation and the assessment never persists (#2456).
    """
    from app.domain.models.course_quality import UnitQualityAssessment

    assert UnitQualityAssessment.__table__.c.run_id.nullable is True


# ---- Stranded active runs (#2553) --------------------------------------


def _make_run(status: str, started_seconds_ago: int | None, created_seconds_ago: int = 0):
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.domain.models.course_quality import CourseQualityRun

    now = datetime.now(UTC)
    run = CourseQualityRun(
        course_id=uuid.uuid4(),
        run_kind="full",
        status=status,
        budget_credits=0,
    )
    run.started_at = (
        now - timedelta(seconds=started_seconds_ago) if started_seconds_ago is not None else None
    )
    run.created_at = now - timedelta(seconds=created_seconds_ago)
    return run


def test_stale_run_detection_scoring_past_hard_limit():
    from app.domain.services.quality_agent_service import (
        STALE_ACTIVE_RUN_SECONDS,
        is_stale_active_run,
    )

    assert is_stale_active_run(_make_run("scoring", STALE_ACTIVE_RUN_SECONDS + 60))
    assert not is_stale_active_run(_make_run("scoring", STALE_ACTIVE_RUN_SECONDS - 60))


def test_stale_run_detection_ignores_terminal_statuses():
    from app.domain.services.quality_agent_service import (
        STALE_ACTIVE_RUN_SECONDS,
        is_stale_active_run,
    )

    old = STALE_ACTIVE_RUN_SECONDS + 3600
    for status in ("completed", "failed", "cancelled"):
        assert not is_stale_active_run(_make_run(status, old))


def test_stale_run_detection_queued_never_started_uses_created_at():
    """A run whose dispatch was lost never gets started_at — fall back to
    created_at so it can still be re-armed."""
    from app.domain.services.quality_agent_service import (
        STALE_ACTIVE_RUN_SECONDS,
        is_stale_active_run,
    )

    stale = _make_run("queued", None, created_seconds_ago=STALE_ACTIVE_RUN_SECONDS + 60)
    fresh = _make_run("queued", None, created_seconds_ago=60)
    assert is_stale_active_run(stale)
    assert not is_stale_active_run(fresh)


def test_stale_run_detection_handles_naive_timestamps():
    from datetime import datetime, timedelta

    from app.domain.services.quality_agent_service import (
        STALE_ACTIVE_RUN_SECONDS,
        is_stale_active_run,
    )

    run = _make_run("scoring", STALE_ACTIVE_RUN_SECONDS + 60)
    run.started_at = datetime.utcnow() - timedelta(seconds=STALE_ACTIVE_RUN_SECONDS + 60)
    assert is_stale_active_run(run)


@pytest.mark.asyncio
async def test_assess_course_requeues_stale_run_on_idempotency_conflict():
    """A same-day zombie run (stuck in 'scoring' past the hard limit) must be
    re-armed to 'queued' so callers re-dispatch, instead of being reused
    forever (#2553)."""
    from unittest.mock import AsyncMock, MagicMock

    from sqlalchemy.exc import IntegrityError

    from app.domain.services.quality_agent_service import (
        STALE_ACTIVE_RUN_SECONDS,
        CourseQualityService,
    )

    zombie = _make_run("scoring", STALE_ACTIVE_RUN_SECONDS + 600)
    zombie.notes = None

    result = MagicMock()
    result.scalar_one_or_none.return_value = zombie

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock(side_effect=[IntegrityError("x", "y", Exception("dup")), None])
    session.rollback = AsyncMock()
    session.execute = AsyncMock(return_value=result)

    service = CourseQualityService(MagicMock(), MagicMock())
    run = await service.assess_course(
        course_id=zombie.course_id,
        triggered_by_user_id=None,
        session=session,
    )

    assert run is zombie
    assert run.status == "queued"
    assert run.started_at is None
    assert "[stale run re-queued]" in (run.notes or "")


def test_assess_course_task_marks_run_failed_on_crash(monkeypatch):
    """When the sweep dies (worker error, soft time limit), the run row must
    be stamped 'failed' — otherwise it strands in 'scoring' (#2553)."""
    import uuid

    from app.tasks import quality_assessment as qa

    marked: dict = {}

    async def _fake_mark(run_id: str, error: str) -> None:
        marked["run_id"] = run_id
        marked["error"] = error

    def _boom(settings):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(qa, "_mark_run_failed", _fake_mark)
    monkeypatch.setattr(qa, "_make_session_factory", _boom)

    result = qa.assess_course_task.apply(kwargs={"run_id": str(uuid.uuid4())}).get()

    assert result["status"] == "failed"
    assert "db exploded" in result["error"]
    assert marked["run_id"] == result["run_id"]
