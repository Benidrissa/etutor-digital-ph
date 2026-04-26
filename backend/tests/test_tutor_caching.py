"""Tests for the cacheable system-prompt assembly + rich-context companion mode (#1984)."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ai.prompts.tutor import (
    TutorContext,
    get_learner_block_text,
    get_persona_block_text,
    get_socratic_system_prompt,
)
from app.domain.services.tutor_service import (
    _assemble_cached_system,
    _build_course_block,
    _build_current_module_section,
    _render_case_full,
    _render_lesson_full,
    _render_quiz_full,
)


def _ctx(**overrides) -> TutorContext:
    base = dict(
        user_level=2,
        user_language="fr",
        user_country="SN",
        module_id=str(uuid.uuid4()),
        module_title="Introduction",
        module_number=1,
        course_title="Santé Publique",
        course_domain="Santé Publique",
    )
    base.update(overrides)
    return TutorContext(**base)


def _unit(unit_number, title_fr, title_en, order_index):
    return SimpleNamespace(
        unit_number=unit_number,
        title_fr=title_fr,
        title_en=title_en,
        order_index=order_index,
    )


def _module(units, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title_fr=extra.get("title_fr", "Module Un"),
        title_en=extra.get("title_en", "Module One"),
        module_number=extra.get("number", 1),
        course_id=extra.get("course_id", uuid.uuid4()),
        case_study_fr=extra.get("case_study_fr"),
        case_study_en=extra.get("case_study_en"),
        units=units,
    )


def _course(modules=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        title_fr="Santé Publique AOF",
        title_en="Public Health AOF",
        domain="Santé Publique",
        syllabus_context="Module 1 — Intro\n- 1.1 Définitions\n- 1.2 Histoire",
        syllabus_json=None,
        rag_collection_id=None,
    )


def _row(content_type, language, content):
    return SimpleNamespace(content_type=content_type, language=language, content=content)


def _mock_session(rows_per_call=None):
    """Session mock whose ``execute`` returns the rows queued per call."""
    rows_per_call = list(rows_per_call or [])

    def _result_for(rows):
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=rows)
        # Also support ``.all()`` directly on the result for the
        # cross-module-id query (returns tuples).
        result = MagicMock()
        result.scalars = MagicMock(return_value=scalars)
        result.all = MagicMock(return_value=[])
        return result

    results = [_result_for([])] if not rows_per_call else [_result_for(r) for r in rows_per_call]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=results)
    return session


# --- _assemble_cached_system -------------------------------------------------


def test_assemble_returns_four_blocks_when_all_layers_present():
    blocks = _assemble_cached_system("PERSONA", "COURSE", "MODULE", "LEARNER")
    assert len(blocks) == 4
    assert [b["text"] for b in blocks] == ["PERSONA", "COURSE", "MODULE", "LEARNER"]


def test_assemble_first_three_blocks_are_cached_last_is_not():
    blocks = _assemble_cached_system("PERSONA", "COURSE", "MODULE", "LEARNER")
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[2]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in blocks[3]


def test_assemble_skips_optional_blocks_when_empty():
    blocks = _assemble_cached_system("PERSONA", None, None, "LEARNER")
    assert len(blocks) == 2
    assert blocks[0]["text"] == "PERSONA"
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"] == "LEARNER"
    assert "cache_control" not in blocks[1]


def test_assemble_only_module_block_is_cacheable_even_without_course():
    blocks = _assemble_cached_system("PERSONA", None, "MODULE", "LEARNER")
    assert len(blocks) == 3
    assert blocks[1]["text"] == "MODULE"
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


# --- block layering: persona vs learner -------------------------------------


def test_persona_block_does_not_contain_learner_specific_fields():
    persona = get_persona_block_text(_ctx(progress_snapshot="Niveau 2", learner_memory="memory"))
    assert "Niveau 2" not in persona
    assert "memory" not in persona
    assert "CONTEXTE DE L" not in persona


def test_learner_block_does_not_contain_pedagogical_rules_or_tools():
    learner = get_learner_block_text(_ctx())
    assert "OUTILS DISPONIBLES" not in learner
    assert "RÈGLES PÉDAGOGIQUES" not in learner
    assert "EXEMPLE DE RÉPONSE" not in learner


def test_persona_blocks_are_byte_identical_when_learner_changes():
    """The persona block is the cache target — it must NOT vary with learner data."""
    a = get_persona_block_text(_ctx(progress_snapshot="A", learner_memory="A", user_country="SN"))
    b = get_persona_block_text(_ctx(progress_snapshot="B", learner_memory="B", user_country="SN"))
    assert a == b


def test_persona_blocks_differ_when_course_or_audience_changes():
    en = get_persona_block_text(_ctx(user_language="en"))
    fr = get_persona_block_text(_ctx(user_language="fr"))
    assert en != fr
    kid = get_persona_block_text(_ctx(is_kids=True, age_min=8, age_max=10))
    adult = get_persona_block_text(_ctx(is_kids=False))
    assert kid != adult


def test_learner_blocks_change_when_memory_changes():
    a = get_learner_block_text(_ctx(learner_memory="alpha"))
    b = get_learner_block_text(_ctx(learner_memory="beta"))
    assert a != b


# --- legacy single-string path still works ---------------------------------


def test_get_socratic_system_prompt_still_returns_a_string():
    """Legacy callers (tests, kill-switch fallback) keep working."""
    out = get_socratic_system_prompt(_ctx(), [])
    assert isinstance(out, str)
    assert "RÈGLES PÉDAGOGIQUES" in out or "EXPLICATIVE" in out


# --- full-content renderers -------------------------------------------------


def test_render_lesson_full_emits_canonical_sections():
    lesson = {
        "introduction": "intro paragraph",
        "concepts": ["c1", "c2"],
        "aof_example": "AOF example body",
        "synthesis": "syn paragraph",
        "key_points": ["kp1", "kp2"],
        "sources_cited": ["Donaldson Ch.4, p.67"],
    }
    out = _render_lesson_full(lesson, max_chars=10000, language="fr")
    assert "intro paragraph" in out
    assert "c1" in out and "c2" in out
    assert "AOF example body" in out
    assert "syn paragraph" in out
    assert "kp1" in out and "kp2" in out
    assert "Donaldson Ch.4, p.67" in out


def test_render_quiz_full_renders_questions_and_answers_when_enabled():
    quiz = {
        "questions": [
            {
                "question": "What is X?",
                "options": ["Option A", "Option B", "Option C", "Option D"],
                "correct_answer": 1,
                "explanation": "Because B is the right one",
            }
        ]
    }
    with_answers = _render_quiz_full(quiz, max_chars=10000, language="en", include_answers=True)
    assert "What is X?" in with_answers
    assert "Option B" in with_answers
    assert "Correct answer" in with_answers
    assert "Because B is the right one" in with_answers
    no_answers = _render_quiz_full(quiz, max_chars=10000, language="en", include_answers=False)
    assert "What is X?" in no_answers
    assert "Correct answer" not in no_answers
    assert "Because B" not in no_answers


def test_render_case_full_handles_structured_and_legacy_text():
    structured = {
        "aof_context": "Côte d'Ivoire context",
        "real_data": "data table",
        "guided_questions": ["q1", "q2"],
        "annotated_correction": "answer body",
        "sources_cited": ["src1"],
    }
    out = _render_case_full(structured, max_chars=5000, language="fr")
    assert "Côte d'Ivoire context" in out
    assert "data table" in out
    assert "q1" in out and "q2" in out
    assert "answer body" in out

    legacy = "Une étude de cas en prose libre."
    out_legacy = _render_case_full(legacy, max_chars=5000, language="fr")
    assert out_legacy == legacy


# --- module block: full content rendering, not 200-char excerpts ----------


@pytest.mark.asyncio
async def test_module_block_marks_unit_generated_when_lesson_exists():
    """Per #1992 spec: generated units show ✓ marker but body is NOT
    inlined — descriptions only, full body via search_knowledge_base."""
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units)
    rows = [
        _row(
            "lesson",
            "fr",
            {
                "unit_id": "1.1",
                "introduction": "Introduction longue avec plusieurs phrases.",
                "concepts": ["concept1", "concept2"],
                "aof_example": "Exemple ouest-africain détaillé",
            },
        )
    ]
    section = await _build_current_module_section(module, "fr", _mock_session([rows]))
    assert section is not None
    assert "Unité 1.1" in section and "Définitions" in section
    assert "✓ généré" in section
    # Body content NOT inlined per the new spec.
    assert "Introduction longue avec plusieurs phrases." not in section
    assert "concept1" not in section


@pytest.mark.asyncio
async def test_module_block_marks_quiz_generated_without_inlining_questions():
    """Quiz body is also no longer inlined — just the marker."""
    units = [_unit("1.1", "Définitions", "Definitions", order_index=1)]
    module = _module(units=units)
    rows = [
        _row(
            "quiz",
            "fr",
            {
                "unit_id": "1.1",
                "questions": [
                    {
                        "question": "Quelle est la définition de X ?",
                        "options": ["Op A", "Op B", "Op C", "Op D"],
                        "correct_answer": 2,
                        "explanation": "Parce que C est correcte",
                    }
                ],
            },
        )
    ]
    section = await _build_current_module_section(module, "fr", _mock_session([rows]))
    assert section is not None
    assert "Unité 1.1" in section
    assert "✓ généré" in section
    # Question body must NOT be inlined per #1992.
    assert "Quelle est la définition de X" not in section
    assert "Parce que C est correcte" not in section


# --- course block ----------------------------------------------------------


@pytest.mark.asyncio
async def test_course_block_renders_title_domain_and_full_syllabus():
    course = _course()
    course.syllabus_context = "Long syllabus prose " * 200  # ~4000 chars
    module = _module(units=[])
    # Three execute calls: resources (empty), modules (empty), generated_module_ids (empty)
    session = _mock_session([[], [], []])
    block = await _build_course_block(course, module, "fr", session)
    assert block is not None
    assert "Santé Publique" in block
    assert "Long syllabus prose" in block
    # Full syllabus is no longer trimmed at 1400 — at least 3000 chars present.
    assert len(block) > 3000


@pytest.mark.asyncio
async def test_course_block_returns_none_when_no_course():
    block = await _build_course_block(None, None, "fr", _mock_session())
    assert block is None


@pytest.mark.asyncio
async def test_course_block_skips_resource_section_when_no_summaries():
    course = _course()
    module = _module(units=[])
    session = _mock_session([[], [], []])
    block = await _build_course_block(course, module, "fr", session)
    assert block is not None
    assert "Ressources de référence" not in block


# --- caching invariants ----------------------------------------------------


def test_two_consecutive_persona_blocks_with_same_inputs_are_byte_identical():
    """Cache hit prerequisite — persona text must be deterministic per inputs."""
    ctx_a = _ctx(progress_snapshot="X", learner_memory="Y")
    ctx_b = _ctx(progress_snapshot="A different progress", learner_memory="Different memory")
    a = get_persona_block_text(ctx_a)
    b = get_persona_block_text(ctx_b)
    assert a == b


def test_changing_only_learner_memory_does_not_change_persona_or_module_text():
    """Layer 4 (learner) changes must not bust the cached layers above."""
    ctx_a = _ctx(learner_memory="memory v1")
    ctx_b = _ctx(learner_memory="memory v2")
    persona_a = get_persona_block_text(ctx_a)
    persona_b = get_persona_block_text(ctx_b)
    assert persona_a == persona_b
    learner_a = get_learner_block_text(ctx_a)
    learner_b = get_learner_block_text(ctx_b)
    assert learner_a != learner_b
