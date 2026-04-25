"""Tests for course-syllabus injection into the tutor system prompt (#1979)."""

import pytest

from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt
from app.domain.services.tutor_service import (
    _SYLLABUS_PROMPT_CHAR_LIMIT,
    _build_syllabus_for_prompt,
    _flatten_syllabus_json,
)


def _ctx(course_syllabus: str | None = None, language: str = "fr") -> TutorContext:
    return TutorContext(
        user_level=2,
        user_language=language,
        user_country="SN",
        course_title="Santé Publique",
        course_domain="Santé Publique",
        course_syllabus=course_syllabus,
    )


def test_no_syllabus_means_no_section_in_prompt():
    prompt = get_socratic_system_prompt(_ctx(course_syllabus=None), [])
    assert "SYLLABUS DU COURS" not in prompt
    assert "COURSE SYLLABUS" not in prompt


def test_syllabus_renders_french_header():
    syllabus = "- Module 1: Épidémiologie\n- Module 2: Santé maternelle"
    prompt = get_socratic_system_prompt(_ctx(course_syllabus=syllabus, language="fr"), [])
    assert "## SYLLABUS DU COURS" in prompt
    assert "Module 1: Épidémiologie" in prompt
    assert "Module 2: Santé maternelle" in prompt


def test_syllabus_renders_english_header():
    syllabus = "- Module 1: Epidemiology\n- Module 2: Maternal health"
    prompt = get_socratic_system_prompt(_ctx(course_syllabus=syllabus, language="en"), [])
    assert "## COURSE SYLLABUS" in prompt
    assert "Module 1: Epidemiology" in prompt


def test_build_syllabus_prefers_prose_when_both_available():
    prose = "Module 1: Foo\nModule 2: Bar"
    structured = {"modules": [{"title": "Other"}]}
    out = _build_syllabus_for_prompt(prose, structured)
    assert out == prose


def test_build_syllabus_falls_back_to_json_when_prose_missing():
    structured = {
        "title": "Public Health 101",
        "modules": [
            {"title": "Epidemiology", "units": [{"title": "Disease frequency"}]},
            {"title": "Health systems"},
        ],
    }
    out = _build_syllabus_for_prompt(None, structured)
    assert out is not None
    assert "Public Health 101" in out
    assert "Epidemiology" in out
    assert "Disease frequency" in out
    assert "Health systems" in out


def test_build_syllabus_returns_none_when_both_empty():
    assert _build_syllabus_for_prompt(None, None) is None
    assert _build_syllabus_for_prompt("", {}) is None


def test_build_syllabus_trims_long_input():
    long_syllabus = "Section\n" + ("x" * (_SYLLABUS_PROMPT_CHAR_LIMIT * 2))
    out = _build_syllabus_for_prompt(long_syllabus, None)
    assert out is not None
    assert len(out) <= _SYLLABUS_PROMPT_CHAR_LIMIT + 4  # +trailing ellipsis line
    assert out.endswith("…")


def test_flatten_syllabus_json_handles_list_of_strings():
    out = _flatten_syllabus_json(["First", "Second", "Third"])
    assert "First" in out and "Second" in out and "Third" in out


def test_flatten_syllabus_json_handles_unknown_shape_gracefully():
    # Garbage in, empty (not crash) out.
    assert _flatten_syllabus_json(42) == ""
    assert _flatten_syllabus_json({"unrelated_key": "value"}) == ""


@pytest.mark.parametrize("language", ["fr", "en"])
def test_syllabus_section_includes_usage_hint(language):
    """The section ends with a hint telling the tutor how to use the outline."""
    prompt = get_socratic_system_prompt(
        _ctx(course_syllabus="- Module 1: Foo", language=language), []
    )
    if language == "fr":
        assert "Utilise ce plan" in prompt
    else:
        assert "Use this outline" in prompt
