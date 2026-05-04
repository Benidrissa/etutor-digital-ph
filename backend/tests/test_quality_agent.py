"""Unit tests for the course quality agent (#2215).

Pure-function tests only — no DB, no Anthropic. The end-to-end
integration tests live separately and require a real PostgreSQL +
Anthropic API key.
"""

from __future__ import annotations

import pytest

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
    with pytest.raises(Exception):
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
    with pytest.raises(Exception):
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
        neighbor_digest=[
            {"unit_number": "1.1", "title": "Intro", "summary": "summary 1"}
        ],
        rag_excerpts=[
            {"source": "triola", "chapter": "5", "page": "47", "content": "chunk"}
        ],
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
    if (
        prev_score is not None
        and current_score - prev_score < MIN_IMPROVEMENT_PER_ATTEMPT
    ):
        return True
    return False


def test_loop_stops_when_passing():
    assert _should_stop_loop(
        is_manually_edited=False,
        needs_regen=False,
        current_score=92,
        prev_score=None,
        attempts=0,
    ) is True


def test_loop_continues_when_failing_first_attempt():
    assert _should_stop_loop(
        is_manually_edited=False,
        needs_regen=True,
        current_score=72,
        prev_score=None,
        attempts=0,
    ) is False


def test_loop_stops_at_max_attempts():
    assert _should_stop_loop(
        is_manually_edited=False,
        needs_regen=True,
        current_score=72,
        prev_score=70,
        attempts=MAX_REGEN_ATTEMPTS,
    ) is True


def test_loop_stops_on_oscillation_88_to_90_to_88():
    """88 → 90 (pass), but if it had been 88 → 90 → 88 we'd stop on the third."""
    # 88 first attempt, 90 second — passes the +3 guard? +2 is below +3, so stop.
    assert _should_stop_loop(
        is_manually_edited=False,
        needs_regen=True,
        current_score=90,
        prev_score=88,
        attempts=1,
    ) is True


def test_loop_continues_when_improving_well():
    """50 → 75 (+25) is healthy improvement; keep going."""
    assert _should_stop_loop(
        is_manually_edited=False,
        needs_regen=True,
        current_score=75,
        prev_score=50,
        attempts=1,
    ) is False


def test_loop_stops_immediately_when_locked():
    """Manually edited content always stops, even if score would warrant retry."""
    assert _should_stop_loop(
        is_manually_edited=True,
        needs_regen=True,
        current_score=10,
        prev_score=None,
        attempts=0,
    ) is True


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
    with pytest.raises(Exception):
        DimensionScores(
            terminology_consistency=-1,
            source_grounding=80,
            syllabus_alignment=80,
            internal_contradictions=80,
            pedagogical_fit=80,
            structural_completeness=80,
        )
