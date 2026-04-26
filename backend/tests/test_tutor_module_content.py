"""Tests for current-module unit/quiz/case-study injection (#1981)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.prompts.tutor import TutorContext, get_socratic_system_prompt
from app.domain.services.tutor_service import (
    _build_current_module_section,
    _excerpt_from_generated_content,
)


def _ctx(current_module_content: str | None = None, language: str = "fr") -> TutorContext:
    return TutorContext(
        user_level=2,
        user_language=language,
        user_country="SN",
        module_id=str(uuid.uuid4()),
        module_title="Introduction",
        module_number=1,
        course_title="Santé Publique",
        course_domain="Santé Publique",
        current_module_content=current_module_content,
    )


def _unit(unit_number: str, title_fr: str, title_en: str, order_index: int) -> SimpleNamespace:
    return SimpleNamespace(
        unit_number=unit_number,
        title_fr=title_fr,
        title_en=title_en,
        order_index=order_index,
    )


def _module(units: list, *, title_fr="Module Un", title_en="Module One", number=1, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title_fr=title_fr,
        title_en=title_en,
        module_number=number,
        case_study_fr=extra.get("case_study_fr"),
        case_study_en=extra.get("case_study_en"),
        units=units,
    )


def _mock_session(generated_rows: list | None = None):
    """Build an AsyncSession mock whose ``execute`` returns the given rows."""
    rows = list(generated_rows or [])
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=rows)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _row(content_type: str, language: str, content: dict) -> SimpleNamespace:
    return SimpleNamespace(content_type=content_type, language=language, content=content)


# --- prompt-formatter tests --------------------------------------------------


def test_no_current_module_content_means_no_section_in_prompt():
    prompt = get_socratic_system_prompt(_ctx(current_module_content=None), [])
    assert "DÉTAIL DU MODULE ACTUEL" not in prompt
    assert "CURRENT MODULE DETAIL" not in prompt


def test_section_renders_with_french_header_when_locale_fr():
    rendered = "Module 1 — Intro\n- 1.1 Foo ✓ (généré)"
    prompt = get_socratic_system_prompt(_ctx(current_module_content=rendered, language="fr"), [])
    assert "## DÉTAIL DU MODULE ACTUEL" in prompt
    assert "1.1 Foo" in prompt
    assert "Utilise ce détail" in prompt


def test_section_renders_with_english_header_when_locale_en():
    rendered = "Module 1 — Intro\n- 1.1 Foo ✓ (generated)"
    prompt = get_socratic_system_prompt(_ctx(current_module_content=rendered, language="en"), [])
    assert "## CURRENT MODULE DETAIL" in prompt
    assert "Use this detail" in prompt


# --- excerpt extractor -------------------------------------------------------


def test_excerpt_prefers_summary_then_intro_then_text():
    out = _excerpt_from_generated_content(
        {"text": "FALLBACK", "summary": "Le résumé court."}, max_chars=100
    )
    assert out == "Le résumé court."


def test_excerpt_falls_back_to_first_string_value():
    out = _excerpt_from_generated_content({"unit_id": "1.1", "title": "Hello"}, max_chars=50)
    # `unit_id` is a string but considered metadata; ensure something useful comes out.
    assert "Hello" in out or "1.1" in out


def test_excerpt_handles_quiz_shape_with_questions_array():
    out = _excerpt_from_generated_content({"questions": [{"question": "What is X?"}]}, max_chars=80)
    assert "What is X?" in out


def test_excerpt_truncates_on_word_boundary_with_ellipsis():
    long_text = "word " * 200  # 1000 chars
    out = _excerpt_from_generated_content({"summary": long_text}, max_chars=50)
    assert out.endswith("…")
    assert len(out) <= 60


def test_excerpt_returns_empty_for_empty_or_none():
    assert _excerpt_from_generated_content(None, max_chars=100) == ""
    assert _excerpt_from_generated_content({}, max_chars=100) == ""
    assert _excerpt_from_generated_content("", max_chars=100) == ""


# --- _build_current_module_section -----------------------------------------


@pytest.mark.asyncio
async def test_no_module_means_no_section():
    section = await _build_current_module_section(None, "fr", _mock_session())
    assert section is None


@pytest.mark.asyncio
async def test_module_with_no_units_returns_none():
    module = _module(units=[])
    section = await _build_current_module_section(module, "fr", _mock_session())
    assert section is None  # nothing useful to say


@pytest.mark.asyncio
async def test_renders_unit_titles_with_pending_status_when_no_generated_content():
    """Per #1992 spec: every unit's number + title visible regardless of size,
    pending units flagged as such, no full-body content."""
    units = [
        _unit("1.1", "Définitions", "Definitions", order_index=1),
        _unit("1.2", "Histoire", "History", order_index=2),
    ]
    module = _module(units=units)
    section = await _build_current_module_section(module, "fr", _mock_session([]))
    assert section is not None
    assert "Unité 1.1" in section and "Définitions" in section
    assert "Unité 1.2" in section and "Histoire" in section
    assert "🔒 à venir" in section
    assert "✓ généré" not in section


@pytest.mark.asyncio
async def test_renders_generated_marker_when_content_exists():
    """Per #1992: generated units show ✓ marker but do NOT inline the body
    (tutor calls search_knowledge_base for full content)."""
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units)
    rows = [
        _row(
            "lesson",
            "fr",
            {"unit_id": "1.1", "summary": "Ce chapitre introduit les notions clés."},
        )
    ]
    section = await _build_current_module_section(module, "fr", _mock_session(rows))
    assert section is not None
    assert "Unité 1.1" in section
    assert "✓ généré" in section
    # Body content must NOT be inlined per #1992 spec — descriptions only.
    assert "Ce chapitre introduit les notions clés." not in section


@pytest.mark.asyncio
async def test_picks_french_or_english_per_locale():
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units)
    fr_section = await _build_current_module_section(module, "fr", _mock_session([]))
    en_section = await _build_current_module_section(module, "en", _mock_session([]))
    assert "Définitions" in fr_section
    assert "Definitions" in en_section
    assert "Définitions" not in en_section
    assert "Definitions" not in fr_section
    assert "🔒 à venir" in fr_section
    assert "🔒 pending" in en_section
    # Localised units header.
    assert "Unités" in fr_section
    assert "Units" in en_section


@pytest.mark.asyncio
async def test_module_level_case_study_text_columns_used_when_no_generated_row():
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(
        units=units,
        case_study_fr="Une étude de cas sur Ebola en 2014 — riposte coordonnée régionale.",
    )
    section = await _build_current_module_section(module, "fr", _mock_session([]))
    assert section is not None
    assert "Étude de cas" in section
    assert "Ebola" in section


@pytest.mark.asyncio
async def test_generated_case_row_preferred_over_legacy_text_column():
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units, case_study_fr="OLD legacy case study text.")
    rows = [_row("case", "fr", {"title": "Riposte Ebola", "summary": "Coordination régionale."})]
    section = await _build_current_module_section(module, "fr", _mock_session(rows))
    assert section is not None
    assert "Riposte Ebola" in section
    # Per #1992 spec: case body content is no longer inlined when a generated
    # case row exists — the title+marker is enough; full body via tool_use.
    assert "OLD legacy" not in section
    assert "Coordination régionale" not in section


@pytest.mark.asyncio
async def test_total_section_capped_at_char_limit():
    # Build an absurdly large module — many units, long summaries.
    units = [
        _unit(f"1.{i}", f"Titre {i} " * 10, f"Title {i} " * 10, order_index=i) for i in range(40)
    ]
    module = _module(units=units)
    rows = [
        _row("lesson", "fr", {"unit_id": f"1.{i}", "summary": "Lorem " * 200}) for i in range(40)
    ]
    section = await _build_current_module_section(
        module, "fr", _mock_session(rows), char_limit=500, excerpt_chars=200
    )
    assert section is not None
    assert len(section) <= 510  # cap + the trailing "\n…"
    assert section.endswith("…")


@pytest.mark.asyncio
async def test_units_sorted_by_order_index():
    units = [
        _unit("1.3", "Trois", "Three", order_index=3),
        _unit("1.1", "Un", "One", order_index=1),
        _unit("1.2", "Deux", "Two", order_index=2),
    ]
    module = _module(units=units)
    section = await _build_current_module_section(module, "fr", _mock_session([]))
    assert section is not None
    pos_1 = section.find("Un")
    pos_2 = section.find("Deux")
    pos_3 = section.find("Trois")
    assert 0 <= pos_1 < pos_2 < pos_3


@pytest.mark.asyncio
async def test_db_failure_does_not_explode_returns_titles_only():
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units)
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    section = await _build_current_module_section(module, "fr", session)
    # Falls through to titles-only; no crash.
    assert section is not None
    assert "Définitions" in section
    assert "🔒 à venir" in section
