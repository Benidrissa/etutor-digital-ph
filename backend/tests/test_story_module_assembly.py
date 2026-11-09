"""The module story assembler (contract C-2), on real chapter documents.

The fixture ``fixtures/module_story_chapters.json`` holds a module of six
units — lessons 1.1 and 1.2, the quiz unit 1.3 (the covering quiz of every
lesson: 1.6 comes after the module's last quiz), the case study 1.4, lesson
1.5 whose chapter is not ready, and lesson 1.6 — and the
three ready lessons' chapter documents in English and French, made by the
real chapter pipeline (:meth:`StoryFromLessonService.generate_document`, a
fake model returning the ``lesson_story_unit.json`` spines). The covering
quiz's ``option_misconceptions`` are sentinel strings, so a test can prove
they never reach a story. ``test_the_fixture_is_what_the_builder_makes``
rebuilds the chapters and fails when the builder changes; regenerate with::

    STORY_FIXTURE_REGEN=1 uv run pytest tests/test_story_module_assembly.py \
        -k the_fixture_is_what_the_builder_makes

The picks are chosen to exercise de-duplication: 1.2 picks one question 1.1
already asked (dropped: 1.2 keeps two), and 1.6 picks two questions 1.2
asked (both kept by the floor rule: 1.6 would be left with one).
"""

from __future__ import annotations

import copy
import json
import os
import random
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_module_assembly as assembly
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    MAX_REPAIR_CALLS,
    StoryFromLessonService,
)
from app.domain.services.story_module_assembly import (
    ChapterSource,
    ModuleStoryContext,
    StoryUnit,
    assemble_module_story,
    module_story_slug,
    unit_role,
    validate_module_story,
)

FIXTURES = Path(__file__).parent / "fixtures"
LESSON_FIXTURE = FIXTURES / "lesson_story_unit.json"
MODULE_FIXTURE = FIXTURES / "module_story_chapters.json"

SENTINEL = "SENTINEL-OPTION-MISCONCEPTION"
LANGUAGES = ("en", "fr")

MODULE = {
    "module_id": "5e1d2c3b-4a59-4687-9a6b-5c4d3e2f1a0b",
    "module_number": 1,
    "module_title": {"en": "Malaria control", "fr": "Lutte contre le paludisme"},
    "course_title": {"en": "Public health", "fr": "Santé publique"},
    "previous_module": None,
    "is_kids": False,
}

UNITS = [
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000011",
        "unit_number": "1.1",
        "unit_type": "lesson",
        "order_index": 0,
        "title": {"en": "How malaria spreads", "fr": "Comment le paludisme se transmet"},
    },
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000012",
        "unit_number": "1.2",
        "unit_type": "lesson",
        "order_index": 1,
        "title": {
            "en": "Preventing malaria in children",
            "fr": "Prévenir le paludisme chez l'enfant",
        },
    },
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000013",
        "unit_number": "1.3",
        "unit_type": "quiz",
        "order_index": 2,
        "title": {"en": "Quiz: malaria basics", "fr": "Quiz : les bases du paludisme"},
    },
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000014",
        "unit_number": "1.4",
        "unit_type": "case-study",
        "order_index": 3,
        "title": {"en": "A fever in Kaya", "fr": "Une fièvre à Kaya"},
    },
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000015",
        "unit_number": "1.5",
        "unit_type": "lesson",
        "order_index": 4,
        "title": {"en": "Treating simple malaria", "fr": "Traiter le paludisme simple"},
    },
    {
        "module_unit_id": "0d6f1e5a-1111-4c2b-9a3e-000000000016",
        "unit_number": "1.6",
        "unit_type": None,
        "order_index": 5,
        "title": {"en": "Working with the community", "fr": "Travailler avec la communauté"},
    },
]

#: The covering quiz's candidate refs each lesson's spine picks (q2..q5 are
#: the lesson fixture's q1..q4; q1 and q6 are about other lessons), and
#: whether its spine keeps its extra questions.
RECIPES = {
    "1.1": {"picks": ["q2", "q3"], "extra_questions": True},
    "1.2": {"picks": ["q3", "q4", "q5"], "extra_questions": False},
    "1.6": {"picks": ["q4", "q5"], "extra_questions": False},
}

#: The quiz unit's two questions about other lessons.
OTHER_MCQS = {
    "en": [
        {
            "id": "tb1",
            "question": "How long does standard tuberculosis treatment last?",
            "options": ["Two weeks", "Six months", "Ten years", "One day"],
            "correct_answer": 1,
            "explanation": "The standard regimen lasts six months.",
        },
        {
            "id": "wash1",
            "question": "When should hands be washed with soap?",
            "options": ["Only on Sundays", "Before eating", "Never", "Once a year"],
            "correct_answer": 1,
            "explanation": "Washing before eating stops germs.",
        },
    ],
    "fr": [
        {
            "id": "tb1",
            "question": "Combien de temps dure le traitement standard de la tuberculose ?",
            "options": ["Deux semaines", "Six mois", "Dix ans", "Un jour"],
            "correct_answer": 1,
            "explanation": "Le schéma standard dure six mois.",
        },
        {
            "id": "wash1",
            "question": "Quand faut-il se laver les mains au savon ?",
            "options": ["Le dimanche", "Avant de manger", "Jamais", "Une fois par an"],
            "correct_answer": 1,
            "explanation": "Se laver avant de manger arrête les microbes.",
        },
    ],
}

REF_TYPES = ("ask", "game", "photo", "video")
BRIDGES = [repair.bridge_line(i) for i in range(3)]


# --------------------------------------------------------------------------
# Building the fixture with the real chapter pipeline
# --------------------------------------------------------------------------


class FakeClaude:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        return copy.deepcopy(self.response)


def covering_quiz(lesson_raw: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Unit 1.3's quiz; every option_misconceptions slot is a sentinel."""
    questions = [
        OTHER_MCQS[language][0],
        *lesson_raw[language]["quiz"]["questions"],
        OTHER_MCQS[language][1],
    ]
    out = []
    for question in copy.deepcopy(questions):
        question["option_misconceptions"] = [
            None if index == question["correct_answer"] else f"{SENTINEL}-{question['id']}-{index}"
            for index in range(len(question["options"]))
        ]
        out.append(question)
    return out


def chapter_spine(lesson_raw: dict[str, Any], language: str, unit_number: str) -> dict[str, Any]:
    recipe = RECIPES[unit_number]
    spine = copy.deepcopy(lesson_raw[language]["spine"])
    for entry in spine["derived"]:
        entry["ref"] = f"q{int(entry['ref'][1:]) + 1}"
    spine["derived"] = [e for e in spine["derived"] if e["ref"] in recipe["picks"]]
    if not recipe["extra_questions"]:
        spine["questions"] = []
    return spine


def chapter_ctx(
    lesson_raw: dict[str, Any], language: str, unit: dict[str, Any]
) -> repair.LessonStoryContext:
    mcqs, dropped = repair.parse_quiz_mcqs(covering_quiz(lesson_raw, language))
    assert dropped == []
    return repair.LessonStoryContext(
        module_unit_id=uuid.UUID(unit["module_unit_id"]),
        language=language,
        unit_number=unit["unit_number"],
        unit_title=dict(unit["title"]),
        module_title=dict(MODULE["module_title"]),
        course_title=dict(MODULE["course_title"]),
        module_number=MODULE["module_number"],
        lesson=copy.deepcopy(lesson_raw[language]["lesson"]),
        mcqs=mcqs,
        has_quiz=True,
        is_kids=MODULE["is_kids"],
        quiz_scope="covering",
        quiz_unit_number="1.3",
    )


async def build_chapters(lesson_raw: dict[str, Any], language: str) -> dict[str, dict[str, Any]]:
    """The ready lessons' chapter documents, exactly as the pipeline stores them."""
    chapters: dict[str, dict[str, Any]] = {}
    for unit in UNITS:
        if unit["unit_number"] not in RECIPES:
            continue
        model = FakeClaude(chapter_spine(lesson_raw, language, unit["unit_number"]))
        generation = await StoryFromLessonService(model).generate_document(
            chapter_ctx(lesson_raw, language, unit), system_prompt="system"
        )
        report = generation.report
        assert report.ok and report.errors == [], [e.model_dump() for e in report.errors]
        assert report.warnings == [], [w.model_dump() for w in report.warnings]
        assert generation.model_calls == 1
        chapters[unit["unit_number"]] = generation.doc
    return chapters


def _undated(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc["checks"].pop("date", None)
    return doc


@pytest.fixture(scope="module")
def lesson_raw() -> dict[str, Any]:
    return json.loads(LESSON_FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))


async def test_the_fixture_is_what_the_builder_makes(lesson_raw):
    chapters = {language: await build_chapters(lesson_raw, language) for language in LANGUAGES}
    if os.environ.get("STORY_FIXTURE_REGEN") == "1":
        data = {
            "_comment": (
                "Module story fixture: a module's units and its ready lessons' chapter"
                " documents, made by the chapter pipeline from lesson_story_unit.json."
                " Regenerate with STORY_FIXTURE_REGEN=1 (see test_story_module_assembly.py)."
            ),
            "module": MODULE,
            "units": UNITS,
            "recipes": RECIPES,
            "quiz": {language: covering_quiz(lesson_raw, language) for language in LANGUAGES},
            "chapters": chapters,
        }
        MODULE_FIXTURE.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    stored = json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))
    assert stored["units"] == UNITS and stored["module"] == MODULE
    assert stored["recipes"] == RECIPES
    for language in LANGUAGES:
        assert stored["quiz"][language] == covering_quiz(lesson_raw, language)
        assert sorted(stored["chapters"][language]) == sorted(RECIPES)
        for number, doc in chapters[language].items():
            assert _undated(stored["chapters"][language][number]) == _undated(doc), number


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def story_units(fixture: dict[str, Any]) -> list[StoryUnit]:
    return [
        StoryUnit(
            module_unit_id=uuid.UUID(unit["module_unit_id"]),
            unit_number=unit["unit_number"],
            unit_type=unit["unit_type"],
            order_index=unit["order_index"],
            role=unit_role(unit["unit_type"]),
            title=dict(unit["title"]),
        )
        for unit in fixture["units"]
    ]


def module_ctx(fixture: dict[str, Any], language: str, **overrides: Any) -> ModuleStoryContext:
    module = fixture["module"]
    values: dict[str, Any] = {
        "module_id": uuid.UUID(module["module_id"]),
        "language": language,
        "module_number": module["module_number"],
        "module_title": dict(module["module_title"]),
        "course_title": dict(module["course_title"]),
        "previous_module": None,
        "is_kids": module["is_kids"],
    }
    values.update(overrides)
    return ModuleStoryContext(**values)


def chapter_sources(fixture: dict[str, Any], language: str) -> list[ChapterSource]:
    docs = fixture["chapters"][language]
    return [
        ChapterSource(unit=unit, doc=copy.deepcopy(docs.get(unit.unit_number)))
        for unit in story_units(fixture)
    ]


def assemble(fixture: dict[str, Any], language: str, **overrides: Any) -> dict[str, Any]:
    return assemble_module_story(
        module_ctx(fixture, language, **overrides), chapter_sources(fixture, language)
    )


def chapter_steps(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for scene in chapter["scenes"] for step in scene["steps"]]


def all_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for chapter in doc["chapters"] for step in chapter_steps(chapter)]


def expected_prefixes(units: list[StoryUnit]) -> list[str]:
    """C-2's ``u{key}-``, a repeated key made unique with ``_2``, ``_3``…"""
    used: set[str] = set()
    out = []
    for unit in units:
        base = "".join(c if c.isascii() and c.isalnum() else "_" for c in unit.unit_number)
        key, n = base, 2
        while key in used:
            key, n = f"{base}_{n}", n + 1
        used.add(key)
        out.append(f"u{key}-")
    return out


def strip(value: Any, prefix: str) -> str:
    assert isinstance(value, str) and value.startswith(prefix), (value, prefix)
    return value[len(prefix) :]


def source_question(question: dict[str, Any], prefix: str) -> dict[str, Any]:
    question = copy.deepcopy(question)
    question["id"] = strip(question["id"], prefix)
    if question.get("objective"):
        question["objective"] = strip(question["objective"], prefix)
    for choice in question.get("choices", []):
        if choice.get("misconception"):
            choice["misconception"] = strip(choice["misconception"], prefix)
    for trap in question.get("traps", []):
        if trap.get("misconception"):
            trap["misconception"] = strip(trap["misconception"], prefix)
    return question


def source_exercise(exercise: dict[str, Any], prefix: str) -> dict[str, Any]:
    exercise = copy.deepcopy(exercise)
    exercise["id"] = strip(exercise["id"], prefix)
    if exercise.get("objective"):
        exercise["objective"] = strip(exercise["objective"], prefix)
    for trap in exercise.get("traps", []):
        if trap.get("misconception"):
            trap["misconception"] = strip(trap["misconception"], prefix)
    return exercise


def source_minigame(game: dict[str, Any], prefix: str) -> dict[str, Any]:
    game = copy.deepcopy(game)
    game["id"] = strip(game["id"], prefix)
    if game.get("objective"):
        game["objective"] = strip(game["objective"], prefix)
    game["traps"] = {k: strip(v, prefix) for k, v in (game.get("traps") or {}).items()}
    if not game["traps"]:
        game.pop("traps")
    for round_data in game.get("rounds", []):
        for item in round_data.get("items", []) if isinstance(round_data, dict) else []:
            if item.get("trap"):
                item["trap"] = strip(item["trap"], prefix)
    return game


def source_step(step: dict[str, Any], prefix: str) -> dict[str, Any]:
    step = copy.deepcopy(step)
    if step.get("id"):
        step["id"] = strip(step["id"], prefix)
    if step["type"] in REF_TYPES and step.get("ref"):
        step["ref"] = strip(step["ref"], prefix)
    return step


def with_id(item: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {**item, "id": strip(item["id"], prefix)}


def owned(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [item for item in items if item["id"].startswith(prefix)]


def check_ids_unique(doc: dict[str, Any]) -> None:
    for name in ("objectives", "misconceptions", "questions", "exercises", "minigames", "videos"):
        ids = [item["id"] for item in doc[name]]
        assert len(ids) == len(set(ids)), name
    assert [c["id"] for c in doc["chapters"]] == [f"ch{n + 1}" for n in range(len(doc["chapters"]))]
    scenes = [s["id"] for c in doc["chapters"] for s in c["scenes"]]
    assert scenes == [f"s{n + 1}" for n in range(len(scenes))]
    step_ids = [s["id"] for s in all_steps(doc) if "id" in s]
    assert len(step_ids) == len(set(step_ids))
    assert len({c["id"] for c in doc["cast"]}) == len(doc["cast"])


def check_references_resolve(doc: dict[str, Any]) -> None:
    objectives = {o["id"] for o in doc["objectives"]}
    misconceptions = {m["id"] for m in doc["misconceptions"]}
    cast = {c["id"] for c in doc["cast"]}
    targets = {
        "ask": {q["id"] for q in doc["questions"]},
        "game": {g["id"] for g in doc["minigames"]},
        "photo": {e["id"] for e in doc["exercises"]},
        "video": {v["id"] for v in doc["videos"]},
    }
    for item in (*doc["questions"], *doc["exercises"], *doc["minigames"]):
        assert item.get("objective") is None or item["objective"] in objectives, item["id"]
    for question in doc["questions"]:
        for choice in question.get("choices", []):
            assert choice.get("misconception") is None or choice["misconception"] in misconceptions
    for item in (*doc["questions"], *doc["exercises"]):
        for trap in item.get("traps", []):
            assert trap["misconception"] in misconceptions
    for game in doc["minigames"]:
        assert set((game.get("traps") or {}).values()) <= misconceptions
        for round_data in game["rounds"]:
            for item in round_data.get("items", []):
                assert item.get("trap") is None or item["trap"] in misconceptions
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            assert scene.get("objective") is None or scene["objective"] in objectives
            for step in scene["steps"]:
                if step["type"] in targets:
                    assert step["ref"] in targets[step["type"]], step
                if step["type"] == "say":
                    assert step["who"] in cast
    assert set(doc["tutor"]["scope"]["this_week"]) == objectives
    assert doc["tutor"]["persona"] in cast
    # Every question is asked exactly once.
    asked = [s["ref"] for s in all_steps(doc) if s["type"] == "ask"]
    assert sorted(asked) == sorted(q["id"] for q in doc["questions"])


def check_story_lines(doc: dict[str, Any]) -> None:
    for step in all_steps(doc):
        if step["type"] in ("narrate", "say"):
            assert len(step["en"]) <= 100 and len(step["fr"]) <= 100, step
        if step.get("frame") in assembly.GENERATED_FRAMES and step["type"] in ("narrate", "say"):
            assert "{child}" in step["en"] and "{child}" in step["fr"], step


def copy_key(question: dict[str, Any], language: str) -> tuple[Any, ...]:
    """What makes two derived questions one quiz question: what the learner reads."""
    reading = question.get("stem") or question["prompt"]
    return (
        reading[language],
        tuple(c[language] for c in question["choices"]),
        question["answer"],
    )


def check_no_text_changed(doc: dict[str, Any], sources: list[ChapterSource]) -> None:
    """Every learner-facing item of a ready lesson is its chapter's own, ids aside.

    Steps match the chapter's in order, apart from the documented frame
    edits (opener and ask-tutor dropped, finished -> lesson done), the steps
    of questions dropped as duplicates, and bridge lines.
    """
    prefixes = expected_prefixes([s.unit for s in sources])
    seen_keys: set[tuple[str, str]] = set()
    for index, (source, chapter) in enumerate(zip(sources, doc["chapters"], strict=True)):
        prefix = prefixes[index]
        if chapter["covers"]["status"] != "ready":
            assert not owned(doc["questions"], prefix) and not owned(doc["objectives"], prefix)
            continue
        src = source.doc
        assert src is not None
        kept = {strip(q["id"], prefix) for q in owned(doc["questions"], prefix)}
        dropped = {q["id"] for q in src["questions"]} - kept

        # De-duplication: only later copies, and never below the floor.
        keys = {
            q["id"]: copy_key(q, doc["languages"]["target"])
            for q in src["questions"]
            if isinstance(q.get("derived_from"), dict)
        }
        assert all(qid in keys and keys[qid] in seen_keys for qid in dropped)
        assert len(kept) >= min(len(src["questions"]), repair.MIN_QUESTIONS)
        kept_copies = [qid for qid in kept if qid in keys and keys[qid] in seen_keys]
        if kept_copies:
            assert len(kept) == repair.MIN_QUESTIONS  # kept only by the floor
        seen_keys.update(keys.values())

        module_questions = {
            strip(q["id"], prefix): source_question(q, prefix)
            for q in owned(doc["questions"], prefix)
        }
        for question in src["questions"]:
            if question["id"] in kept:
                expected = {k: v for k, v in question.items() if k != "option_misconceptions"}
                assert module_questions[question["id"]] == expected
        assert [with_id(o, prefix) for o in owned(doc["objectives"], prefix)] == (src["objectives"])
        assert [source_exercise(e, prefix) for e in owned(doc["exercises"], prefix)] == (
            src["exercises"]
        )
        assert [source_minigame(g, prefix) for g in owned(doc["minigames"], prefix)] == (
            src["minigames"]
        )
        declared = [with_id(m, prefix) for m in owned(doc["misconceptions"], prefix)]
        assert all(m in src["misconceptions"] for m in declared)
        if not dropped:
            assert declared == src["misconceptions"]

        situations = {repair.situation_step_id(qid) for qid in dropped}
        expected_steps = []
        for step in (s for c in src["chapters"] for sc in c["scenes"] for s in sc["steps"]):
            if step.get("frame") in ("opener", "ask_tutor") or step in BRIDGES:
                continue
            if step["type"] == "ask" and step["ref"] in dropped:
                continue
            if step["type"] == "concept" and step["id"] in situations:
                continue
            expected_steps.append("LESSON_DONE" if step.get("frame") == "finished" else step)
        module_steps = []
        for step in chapter_steps(chapter):
            if step in BRIDGES:
                continue
            if step.get("frame") == "lesson_done":
                module_steps.append("LESSON_DONE")
            elif step.get("frame") not in assembly.GENERATED_FRAMES:
                module_steps.append(source_step(step, prefix))
        assert module_steps == expected_steps


def revision_of(sources: list[ChapterSource], statuses: list[str]) -> str:
    """C-2's revision, computed independently of the assembler."""
    import hashlib

    def canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    rows = [
        [
            str(s.unit.module_unit_id),
            s.unit.role,
            hashlib.sha256(canonical(s.doc).encode()).hexdigest() if status == "ready" else None,
        ]
        for s, status in zip(sources, statuses, strict=True)
    ]
    return hashlib.sha256(canonical(rows).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# The fixture module
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_fixture_module_validates_with_zero_errors_and_zero_warnings(fixture, language):
    doc = assemble(fixture, language)
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    assert report.errors == [] and report.warnings == [], [w.model_dump() for w in report.warnings]
    # The same verdict from the bare validator, on a JSON round trip.
    direct = validate_story_course(StoryCourse.model_validate(json.loads(json.dumps(doc))))
    assert direct.ok and direct.warnings == []
    assert report.checks.questions == len(doc["questions"]) == 6 + (language == "en")


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_header_follows_the_contract(fixture, language):
    doc = assemble(fixture, language)
    module_id = uuid.UUID(fixture["module"]["module_id"])
    title = fixture["module"]["module_title"]
    assert doc["format"] == "story-course/1"
    assert (
        doc["id"] == module_story_slug(module_id, language) == f"module-{module_id.hex}-{language}"
    )
    assert doc["course"] == fixture["module"]["course_title"][language]
    assert doc["unit"] == f"Module 1 · {title[language]}"
    assert doc["week"] == 1
    assert doc["title"] == title
    assert doc["languages"] == {"target": language, "home": "fr" if language == "en" else "en"}
    assert doc["learner"] == {"first_name": "{child}"}
    assert doc["cast"] == repair.pinned_cast(False, language)
    assert set(doc["checks"]) == {"predicted_typical"}
    assert set(doc["checks"]["predicted_typical"]) == {"plan", "points"}
    assert doc["module_story"] == {
        "module_id": str(module_id),
        "module_number": 1,
        "assembler": assembly.MODULE_ASSEMBLER_VERSION,
        "revision": doc["module_story"]["revision"],
    }
    assert assembly.MODULE_ASSEMBLER_VERSION == 1
    assert "sira_builder" not in doc


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_chapter_per_unit_in_order_with_its_covers(fixture, language):
    doc = assemble(fixture, language)
    expected = [
        ("1.1", "lesson", "lesson", "ready", True),
        ("1.2", "lesson", "lesson", "ready", True),
        ("1.3", "quiz", "quiz_checkpoint", "checkpoint", False),
        ("1.4", "case-study", "case_checkpoint", "checkpoint", False),
        ("1.5", "lesson", "lesson", "unavailable", False),
        ("1.6", None, "lesson", "ready", True),
    ]
    assert [c["id"] for c in doc["chapters"]] == ["ch1", "ch2", "ch3", "ch4", "ch5", "ch6"]
    for chapter, unit, (number, kind, role, status, completes) in zip(
        doc["chapters"], fixture["units"], expected, strict=True
    ):
        covers = chapter["covers"]
        assert covers["module_unit_id"] == unit["module_unit_id"]
        assert (covers["unit_number"], covers["unit_type"], covers["role"]) == (number, kind, role)
        assert (covers["status"], covers["completes_unit"]) == (status, completes)
        assert chapter["title"] == {
            "en": f"{number} · {unit['title']['en']}",
            "fr": f"{number} · {unit['title']['fr']}",
        }


@pytest.mark.parametrize("language", LANGUAGES)
def test_max_points_per_chapter_add_up_to_the_module(fixture, language):
    doc = assemble(fixture, language)
    chapters = fixture["chapters"][language]
    points = {c["covers"]["unit_number"]: c["covers"]["max_points"] for c in doc["chapters"]}
    # Untouched chapters: their own validated max_points.
    assert points["1.1"] == chapters["1.1"]["checks"]["max_points"] > 0
    assert points["1.6"] == chapters["1.6"]["checks"]["max_points"] > 0
    # 1.2 lost one duplicate question (first try: 2 points).
    assert points["1.2"] == chapters["1.2"]["checks"]["max_points"] - 2
    assert points["1.3"] == points["1.4"] == points["1.5"] == 0
    assert sum(points.values()) == validate_module_story(doc).checks.max_points
    typical = doc["checks"]["predicted_typical"]["points"]
    assert 0 < typical <= sum(points.values())


@pytest.mark.parametrize("language", LANGUAGES)
def test_ids_are_unique_and_every_reference_resolves(fixture, language):
    doc = assemble(fixture, language)
    check_ids_unique(doc)
    check_references_resolve(doc)
    # Namespaced exactly as C-2 says: "u{key}-{original id}".
    assert {q["id"] for q in doc["questions"]} >= {"u1_1-q2", "u1_2-q4", "u1_6-q4", "u1_6-q5"}
    assert "u1_2-q3" not in {q["id"] for q in doc["questions"]}


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_learner_facing_text_changes(fixture, language):
    doc = assemble(fixture, language)
    check_no_text_changed(doc, chapter_sources(fixture, language))


@pytest.mark.parametrize("language", LANGUAGES)
def test_quiz_mcqs_stay_verbatim(fixture, language):
    doc = assemble(fixture, language)
    quiz = {q["id"]: q for q in fixture["quiz"][language]}
    derived = [q for q in doc["questions"] if "derived_from" in q]
    assert len(derived) == 6  # 1.1: 2, 1.2: 2 of its 3, 1.6: 2
    for question in derived:
        assert question["derived_from"]["quiz_unit"] == "1.3"
        mcq = quiz[question["derived_from"]["question_id"]]
        assert [c[language] for c in question["choices"]] == mcq["options"]
        assert question["answer"] == "abcdef"[mcq["correct_answer"]]
        assert question.get("stem", question["prompt"])[language] == mcq["question"]
        assert question["explanation"][language] == mcq["explanation"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_copy_is_dropped_unless_its_chapter_would_fall_below_the_floor(fixture, language):
    doc = assemble(fixture, language)
    by_chapter = {
        number: [q for q in doc["questions"] if q["id"].startswith(f"u{number.replace('.', '_')}-")]
        for number in ("1.1", "1.2", "1.6")
    }
    source = lambda q: q["derived_from"]["question_id"]  # noqa: E731
    assert [source(q) for q in by_chapter["1.1"] if "derived_from" in q] == ["q1", "q2"]
    # 1.2 picked q2 too: 1.1 told it first, and 1.2 keeps two without it.
    assert [source(q) for q in by_chapter["1.2"]] == ["q3", "q4"]
    assert not [s for s in all_steps(doc) if s.get("ref") == "u1_2-q3"]
    assert not [s for s in all_steps(doc) if s.get("id") == "u1_2-situation-q3"]
    # 1.6 repeats 1.2's two, but dropping either would leave it one question.
    assert [source(q) for q in by_chapter["1.6"]] == ["q3", "q4"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_checkpoint_and_placeholder_chapters(fixture, language):
    doc = assemble(fixture, language)
    for index in (2, 3, 4):  # 1.3 quiz, 1.4 case study, 1.5 not ready
        chapter = doc["chapters"][index]
        steps = chapter_steps(chapter)
        assert chapter["covers"]["completes_unit"] is False
        assert chapter["covers"]["max_points"] == 0
        assert not [s for s in steps if s["type"] in REF_TYPES]
        assert {s["frame"] for s in steps} <= set(assembly.GENERATED_FRAMES)
        unit = fixture["units"][index]
        concept = next(s for s in steps if s["type"] == "concept")
        assert concept["en"] == [unit["title"]["en"]] and concept["fr"] == [unit["title"]["fr"]]
    quiz, case, missing = (chapter_steps(doc["chapters"][i]) for i in (2, 3, 4))
    assert quiz[0]["en"] == "Checkpoint, {child}: the quiz of unit 1.3."
    assert quiz[0]["fr"] == "Étape, {child} : le quiz de l'unité 1.3."
    assert quiz[1]["title"] == {"en": "Quiz 1.3", "fr": "Quiz 1.3"}
    assert case[0]["fr"] == "Étape, {child} : l'étude de cas de l'unité 1.4."
    assert case[1]["title"] == {"en": "Case study 1.4", "fr": "Étude de cas 1.4"}
    assert missing[0]["en"] == "Lesson 1.5 is not in the story yet, {child}."
    # The case study's annotated correction is never in the story.
    assert all(s["frame"] == "checkpoint" for s in case)


@pytest.mark.parametrize("language", LANGUAGES)
def test_frame_lines_are_rewritten_by_marker(fixture, language):
    doc = assemble(fixture, language)
    frames = [s.get("frame") for s in all_steps(doc)]
    assert frames.count("opener") == 1 and all_steps(doc)[0]["frame"] == "opener"
    assert frames.count("module_overview") == 1
    assert frames.count("finished") == 1 and frames.count("ask_tutor") == 1
    assert frames.count("lesson_done") == 3  # one per ready lesson
    assert frames.count("objectives") == 3  # kept, one per ready lesson
    assert frames.count("checkpoint_reminder") == 1
    last = chapter_steps(doc["chapters"][-1])
    assert [s.get("frame") for s in last[-3:]] == ["finished", "checkpoint_reminder", "ask_tutor"]
    assert last[-1]["who"] == "margo"
    overview = next(s for s in all_steps(doc) if s.get("frame") == "module_overview")
    assert overview["en"] == [
        "1.1 · How malaria spreads",
        "1.2 · Preventing malaria in children",
        "1.3 · Quiz: malaria basics (quiz)",
        "1.4 · A fever in Kaya (case study)",
        "1.5 · Treating simple malaria",
        "1.6 · Working with the community",
    ]
    assert overview["fr"][3] == "1.4 · Une fièvre à Kaya (étude de cas)"
    done = [s for s in all_steps(doc) if s.get("frame") == "lesson_done"]
    assert [s["en"] for s in done] == [
        f"Well done, {{child}}: lesson {n} is done." for n in ("1.1", "1.2", "1.6")
    ]
    assert done[0]["fr"] == "Bravo, {child} : la leçon 1.1 est terminée."
    check_story_lines(doc)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_tutor_is_built_for_the_module(fixture, language):
    doc = assemble(fixture, language, previous_module=(0, {"en": "Basics", "fr": "Bases"}))
    tutor = doc["tutor"]
    assert tutor["persona"] == "margo"
    assert "AI" in tutor["intro"]["en"] and "IA" in tutor["intro"]["fr"]
    assert tutor["scope"]["this_week"] == [o["id"] for o in doc["objectives"]]
    assert (
        tutor["scope"]["earlier_weeks"] == f"Module 0: {'Basics' if language == 'en' else 'Bases'}"
    )
    assert "this module" in tutor["never"][-1]
    assert assemble(fixture, language)["tutor"]["scope"]["earlier_weeks"] is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_sources_are_merged_without_duplicates(fixture, language):
    doc = assemble(fixture, language)
    keys = [(s["kind"], s["ref"]) for s in doc["sources"]]
    assert len(keys) == len(set(keys))
    assert keys.count(("test", "Unit 1.3 quiz")) == 1
    for number in ("1.1", "1.2", "1.6"):
        assert any(kind == "lesson" and ref.startswith(f"Lesson {number} ") for kind, ref in keys)


def test_a_kids_module_uses_the_kids_cast_rewards_and_places(fixture):
    doc = assemble(fixture, "fr", is_kids=True)
    assert doc["cast"] == repair.pinned_cast(True, "fr")
    assert doc["rewards"]["unit"] == {"en": "mangoes", "fr": "mangues"}
    generated = [
        s
        for c in doc["chapters"]
        for s in c["scenes"]
        if all(step.get("frame") in assembly.GENERATED_FRAMES for step in s["steps"])
    ]
    assert generated and {s["place"] for s in generated} == {"classroom"}
    assert validate_module_story(doc).ok
    assert assemble(fixture, "fr")["rewards"]["unit"] == {"en": "points", "fr": "points"}


def other_level_quiz(lesson_raw: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Another quiz row of unit 1.3 (say level 2): the same ids, other questions."""
    quiz = covering_quiz(lesson_raw, language)
    for question in quiz:
        question["question"] = f"LEVEL2 {question['question']}"
        question["options"] = [f"L2 {option}" for option in question["options"]]
        question["explanation"] = f"LEVEL2 {question['explanation']}"
    return quiz


@pytest.mark.parametrize("language", LANGUAGES)
async def test_questions_of_another_quiz_row_with_the_same_ids_are_not_duplicates(
    fixture, lesson_raw, language
):
    """Chapters can come from different quiz rows of one quiz unit (levels, countries).

    Their generated ids are both ``q1..qN``; the questions are not the same,
    so none of 1.2's is dropped as a copy of 1.1's.
    """
    unit = UNITS[1]
    mcqs, dropped = repair.parse_quiz_mcqs(other_level_quiz(lesson_raw, language))
    assert dropped == []
    ctx = replace(chapter_ctx(lesson_raw, language, unit), mcqs=mcqs)
    generation = await StoryFromLessonService(
        FakeClaude(chapter_spine(lesson_raw, language, "1.2"))
    ).generate_document(ctx, system_prompt="system")
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    level2 = generation.doc
    derived = [q for q in level2["questions"] if "derived_from" in q]
    assert len(derived) == 3
    # The same labels as the level-1 chapter 1.1's copies: q2 is in both.
    first = fixture["chapters"][language]["1.1"]
    labels = lambda doc: {  # noqa: E731
        (q["derived_from"]["quiz_unit"], q["derived_from"]["question_id"])
        for q in doc["questions"]
        if "derived_from" in q
    }
    assert labels(first) & labels(level2)
    units = story_units(fixture)
    sources = [
        ChapterSource(units[0], copy.deepcopy(first)),
        ChapterSource(units[1], level2),
    ]

    doc = assemble_module_story(module_ctx(fixture, language), sources)

    assert validate_module_story(doc).ok
    kept = [q for q in owned(doc["questions"], "u1_2-") if "derived_from" in q]
    assert len(kept) == 3
    assert all(q["prompt"][language].startswith("LEVEL2") or q.get("stem") for q in kept)
    check_no_text_changed(doc, sources)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_labelled_with_an_old_quiz_unit_number_is_still_a_copy(fixture, language):
    """A chapter built before its quiz unit was renumbered: the same question, another label."""
    sources = chapter_sources(fixture, language)
    before = sources[1].doc
    assert before is not None
    for question in before["questions"]:
        if "derived_from" in question:
            question["derived_from"]["quiz_unit"] = "1.9"

    doc = assemble_module_story(module_ctx(fixture, language), sources)

    # 1.1 asked q2 first: 1.2's copy is dropped all the same (it keeps two).
    source = lambda q: q["derived_from"]["question_id"]  # noqa: E731
    assert [source(q) for q in owned(doc["questions"], "u1_2-")] == ["q3", "q4"]
    assert validate_module_story(doc).ok
    check_no_text_changed(doc, sources)


async def test_dedup_may_thin_an_objective_which_is_only_a_warning(fixture, lesson_raw):
    """Documented: the floor is per chapter, not per objective.

    A chapter whose two objectives have two questions each can lose both
    questions of one objective to earlier chapters; the module story then
    carries a ``thin_question_coverage`` warning, which never blocks it.
    """
    spine = copy.deepcopy(lesson_raw["en"]["spine"])
    for entry in spine["derived"]:
        entry["ref"] = f"q{int(entry['ref'][1:]) + 1}"  # picks all four, plus x1
    generation = await StoryFromLessonService(FakeClaude(spine)).generate_document(
        chapter_ctx(lesson_raw, "en", UNITS[1]), system_prompt="system"
    )
    assert generation.report.ok and generation.report.warnings == []
    units = story_units(fixture)
    sources = [
        ChapterSource(units[0], copy.deepcopy(fixture["chapters"]["en"]["1.1"])),
        ChapterSource(units[1], generation.doc),
    ]

    doc = assemble_module_story(module_ctx(fixture, "en"), sources)

    report = validate_module_story(doc)
    assert report.ok
    assert {w.code for w in report.warnings} == {"thin_question_coverage"}
    assert len(owned(doc["questions"], "u1_2-")) == len(generation.doc["questions"]) - 2
    check_no_text_changed(doc, sources)


# --------------------------------------------------------------------------
# Spacing across a chapter boundary
# --------------------------------------------------------------------------


def _move_asks(doc: dict[str, Any], refs: list[str], *, to_end: bool) -> None:
    """Move the ask steps of ``refs`` into a scene of their own, at one end."""
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            scene["steps"] = [s for s in scene["steps"] if s.get("ref") not in refs]
    scene = {"id": "s99", "place": "desk", "steps": [{"type": "ask", "ref": r} for r in refs]}
    if to_end:
        doc["chapters"][-1]["scenes"].append(scene)
    else:
        doc["chapters"][0]["scenes"].insert(0, scene)


def test_a_run_of_asks_across_a_chapter_boundary_gets_a_bridge(fixture):
    units = story_units(fixture)
    first = copy.deepcopy(fixture["chapters"]["en"]["1.1"])
    second = copy.deepcopy(fixture["chapters"]["en"]["1.6"])
    _move_asks(first, ["q2", "q3"], to_end=True)  # ...lesson done, ask, ask |
    _move_asks(second, ["q4", "q5"], to_end=False)  # | ask, ask, opening...
    sources = [ChapterSource(units[0], first), ChapterSource(units[5], second)]

    doc = assemble_module_story(module_ctx(fixture, "en"), sources)

    types = [s["type"] for s in all_steps(doc)]
    run = longest = 0
    for kind in types:
        run = run + 1 if kind == "ask" else 0
        longest = max(longest, run)
    assert longest == repair.MAX_ASKS_IN_A_ROW
    head = chapter_steps(doc["chapters"][1])
    assert head[0] == repair.bridge_line(0)  # the module's first bridge
    assert [s["type"] for s in head[:3]] == ["say", "ask", "ask"]
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    check_no_text_changed(doc, sources)


# --------------------------------------------------------------------------
# Revision, determinism, purity, sentinels
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_revision_is_the_documented_digest(fixture, language):
    sources = chapter_sources(fixture, language)
    doc = assemble_module_story(module_ctx(fixture, language), sources)
    statuses = [c["covers"]["status"] for c in doc["chapters"]]
    revision = doc["module_story"]["revision"]
    assert revision == revision_of(sources, statuses)
    assert len(revision) == 16 and int(revision, 16) >= 0
    assert assemble(fixture, language)["module_story"]["revision"] == revision


def test_the_revision_changes_with_a_chapter_and_not_otherwise(fixture):
    base = assemble(fixture, "en")["module_story"]["revision"]
    # Another context (kids, a previous module) is not a chapter change.
    assert assemble(fixture, "en", is_kids=True)["module_story"]["revision"] == base

    sources = chapter_sources(fixture, "en")
    sources[1].doc["questions"][0]["explanation"]["fr"] += " Voilà."
    edited = assemble_module_story(module_ctx(fixture, "en"), sources)["module_story"]
    assert edited["revision"] != base

    sources = chapter_sources(fixture, "en")
    sources[5] = ChapterSource(sources[5].unit, None)
    gone = assemble_module_story(module_ctx(fixture, "en"), sources)["module_story"]
    assert gone["revision"] not in (base, edited["revision"])


@pytest.mark.parametrize("language", LANGUAGES)
def test_assembly_is_deterministic_and_never_mutates_its_inputs(fixture, language):
    sources = chapter_sources(fixture, language)
    before = copy.deepcopy([s.doc for s in sources])
    first = assemble_module_story(module_ctx(fixture, language), sources)
    second = assemble_module_story(module_ctx(fixture, language), sources)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)
    assert [s.doc for s in sources] == before
    # Mutating the output does not reach the inputs either.
    first["questions"][0]["prompt"]["en"] = "changed"
    first["chapters"][1]["scenes"][0]["steps"][0]["en"] = "changed"
    assert [s.doc for s in sources] == before


def test_option_misconceptions_never_reach_a_story(fixture):
    # The covering quiz carried a sentinel in every wrong option's slot.
    assert all(
        any(isinstance(m, str) and m.startswith(SENTINEL) for m in q["option_misconceptions"])
        for language in LANGUAGES
        for q in fixture["quiz"][language]
    )
    for language in LANGUAGES:
        assert SENTINEL not in json.dumps(fixture["chapters"][language], ensure_ascii=False)
        assert SENTINEL not in json.dumps(assemble(fixture, language), ensure_ascii=False)


def test_a_stray_option_misconceptions_key_is_never_copied(fixture):
    sources = chapter_sources(fixture, "en")
    planted = sources[0].doc["questions"][0]
    planted["option_misconceptions"] = [None, f"{SENTINEL}-planted", None, None]
    planted["choices"][1]["option_misconceptions"] = f"{SENTINEL}-nested"
    before = copy.deepcopy(sources[0].doc)

    doc = assemble_module_story(module_ctx(fixture, "en"), sources)

    text = json.dumps(doc, ensure_ascii=False)
    assert SENTINEL not in text and "option_misconceptions" not in text
    assert sources[0].doc == before
    assert validate_module_story(doc).ok


# --------------------------------------------------------------------------
# Unusable chapter documents become placeholders
# --------------------------------------------------------------------------


def _old_builder(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc.pop("sira_builder")
    return doc


def _builder_one(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc["sira_builder"] = 1
    return doc


def _other_language(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    other = copy.deepcopy(fixture["chapters"]["fr"]["1.2"])
    other["id"] = doc["id"]
    return other


def _other_unit(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(fixture["chapters"]["en"]["1.1"])


def _malformed(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc["questions"] = {"q3": "not a list"}
    return doc


def _no_chapters(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc["chapters"] = []
    return doc


@pytest.mark.parametrize(
    "spoil",
    [_old_builder, _builder_one, _other_language, _other_unit, _malformed, _no_chapters, None],
    ids=lambda f: f.__name__.strip("_") if f else "none",
)
def test_an_unusable_chapter_becomes_a_placeholder(fixture, spoil):
    sources = chapter_sources(fixture, "en")
    doc = copy.deepcopy(sources[1].doc)
    sources[1] = ChapterSource(sources[1].unit, spoil(doc, fixture) if spoil else None)

    module = assemble_module_story(module_ctx(fixture, "en"), sources)

    covers = module["chapters"][1]["covers"]
    assert (covers["status"], covers["completes_unit"], covers["max_points"]) == (
        "unavailable",
        False,
        0,
    )
    steps = chapter_steps(module["chapters"][1])
    assert {s["frame"] for s in steps} == {"unavailable"}
    assert not [q for q in module["questions"] if q["id"].startswith("u1_2-")]
    report = validate_module_story(module)
    assert report.ok and report.warnings == [], [e.model_dump() for e in report.errors]
    check_no_text_changed(module, sources)


def test_a_module_with_no_ready_lesson_is_never_publishable(fixture):
    sources = [ChapterSource(s.unit, None) for s in chapter_sources(fixture, "fr")]
    doc = assemble_module_story(module_ctx(fixture, "fr"), sources)
    assert [c["covers"]["status"] for c in doc["chapters"]] == [
        "unavailable",
        "unavailable",
        "checkpoint",
        "checkpoint",
        "unavailable",
        "unavailable",
    ]
    report = validate_module_story(doc)
    assert not report.ok
    assert {e.code for e in report.errors} == {
        "missing_objectives",
        "missing_minigame",
        "too_few_questions",
    }
    assert doc["checks"]["predicted_typical"]["points"] == 0


def test_a_one_unit_module_opens_and_closes_in_its_only_chapter(fixture):
    sources = chapter_sources(fixture, "en")[:1]
    doc = assemble_module_story(module_ctx(fixture, "en"), sources)
    frames = [s.get("frame") for s in all_steps(doc)]
    assert frames[0] == "opener" and frames[-2:] == ["finished", "ask_tutor"]
    assert "checkpoint_reminder" not in frames  # no quiz or case study to do
    assert validate_module_story(doc).ok


# --------------------------------------------------------------------------
# Roles, slug and validation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("unit_type", "has_case", "role"),
    [
        (None, False, "lesson"),
        ("lesson", False, "lesson"),
        ("lesson", True, "lesson"),
        ("quiz", False, "quiz_checkpoint"),
        ("quiz", True, "case_checkpoint"),  # #2163: mislabelled case study
        ("case-study", False, "case_checkpoint"),
        ("scenario", False, "case_checkpoint"),
        ("assessment", False, "quiz_checkpoint"),  # unknown: quiz-gated
    ],
)
def test_unit_roles_follow_the_completion_api(unit_type, has_case, role):
    assert unit_role(unit_type, has_case_content=has_case) == role


def test_a_scenario_unit_is_named_as_one(fixture):
    sources = chapter_sources(fixture, "fr")
    unit = sources[3].unit
    sources[3] = ChapterSource(
        StoryUnit(
            unit.module_unit_id,
            unit.unit_number,
            "scenario",
            unit.order_index,
            "case_checkpoint",
            unit.title,
        ),
        None,
    )
    doc = assemble_module_story(module_ctx(fixture, "fr"), sources)
    steps = chapter_steps(doc["chapters"][3])
    assert steps[0]["fr"] == "Étape, {child} : la mise en situation de l'unité 1.4."
    assert steps[1]["title"] == {"en": "Scenario 1.4", "fr": "Mise en situation 1.4"}
    check_story_lines(doc)


@pytest.mark.parametrize("doc", [{}, {"format": "story-course/2"}, {"id": 7}, []])
def test_validation_never_raises(doc):
    report = validate_module_story(doc)  # type: ignore[arg-type]
    assert not report.ok
    assert [e.code for e in report.errors] == ["malformed_course_file"]
    assert report.checks.errors == 1


# --------------------------------------------------------------------------
# Property test: random rosters
# --------------------------------------------------------------------------

UNIT_NUMBERS = ["1.1", "1.2", "1_2", "2.9", "2.10", "A-1", "x  y", " 3.1.4", "", "1.2", "é.1"]
TYPES = {
    "lesson": [None, "lesson"],
    "quiz_checkpoint": ["quiz", "assessment"],
    "case_checkpoint": ["case-study", "scenario"],
}


def random_roster(rng: random.Random, fixture: dict[str, Any]):
    language = rng.choice(LANGUAGES)
    pool = list(fixture["chapters"][language].values())
    sources: list[ChapterSource] = []
    for index in range(rng.randint(1, 8)):
        role = rng.choice(["lesson", "lesson", "lesson", "quiz_checkpoint", "case_checkpoint"])
        title = rng.choice(
            [{"en": f"Unit {index}", "fr": f"Unité {index}"}, {"en": "Only English"}, {}]
        )
        unit = StoryUnit(
            module_unit_id=uuid.UUID(int=rng.getrandbits(128)),
            unit_number=rng.choice(UNIT_NUMBERS),
            unit_type=rng.choice(TYPES[role]),
            order_index=index,
            role=role,  # type: ignore[arg-type]
            title=title,
        )
        doc = None
        if role == "lesson":
            state = rng.choice(["ready", "ready", "ready", "missing", "old", "foreign"])
            if state != "missing":
                doc = copy.deepcopy(rng.choice(pool))
                doc["id"] = repair.story_slug(unit.module_unit_id, language)
                if state == "old":
                    doc.pop("sira_builder")
                elif state == "foreign":
                    doc["languages"] = {"target": "fr" if language == "en" else "en"}
        sources.append(ChapterSource(unit, doc))
    ctx = ModuleStoryContext(
        module_id=uuid.UUID(int=rng.getrandbits(128)),
        language=language,
        module_number=rng.randint(0, 12),
        module_title=rng.choice([{"en": "M", "fr": "M fr"}, {"fr": "Seulement"}, {}]),
        course_title=rng.choice([{"en": "C", "fr": "C"}, {}]),
        previous_module=rng.choice([None, (1, {"en": "Before", "fr": "Avant"})]),
        is_kids=rng.random() < 0.5,
    )
    return ctx, sources


@pytest.mark.parametrize("seed", range(40))
def test_any_roster_assembles_into_a_sound_story(fixture, seed):
    rng = random.Random(seed)
    ctx, sources = random_roster(rng, fixture)
    before = copy.deepcopy([s.doc for s in sources])

    doc = assemble_module_story(ctx, sources)

    assert [s.doc for s in sources] == before
    again = assemble_module_story(ctx, sources)
    assert json.dumps(again, ensure_ascii=False) == json.dumps(doc, ensure_ascii=False)
    assert len(doc["chapters"]) == len(sources)
    for chapter, source in zip(doc["chapters"], sources, strict=True):
        assert chapter["covers"]["module_unit_id"] == str(source.unit.module_unit_id)
        assert chapter["covers"]["role"] == source.unit.role
        assert chapter["covers"]["completes_unit"] == (chapter["covers"]["status"] == "ready")
    check_ids_unique(doc)
    check_references_resolve(doc)
    check_story_lines(doc)
    check_no_text_changed(doc, sources)

    report = validate_module_story(doc)
    ready = sum(c["covers"]["status"] == "ready" for c in doc["chapters"])
    if ready:
        assert report.ok, [e.model_dump() for e in report.errors]
        assert report.warnings == [], [w.model_dump() for w in report.warnings]
        assert sum(c["covers"]["max_points"] for c in doc["chapters"]) == (report.checks.max_points)
    else:
        assert {e.code for e in report.errors} <= {
            "missing_objectives",
            "missing_minigame",
            "too_few_questions",
        }


@pytest.mark.parametrize("fault", ["no_distractors", "undeclared_ids"])
@pytest.mark.parametrize("language", LANGUAGES)
async def test_a_gap_the_model_leaves_is_never_filled_from_option_misconceptions(
    lesson_raw, fixture, language, fault
):
    """The real chapter pipeline, then the assembler, on the two fallback paths.

    The covering quiz carries a sentinel in every option_misconceptions slot.
    Lesson 1.1's spine (every repair answer too) gives the wrong options of the
    quiz questions it picks either no misconception at all, or one whose id it
    never declared. Neither gap is ever filled with the course's text: not in
    the chapter, not in the module story.
    """
    unit = next(u for u in UNITS if u["unit_number"] == "1.1")
    spine = chapter_spine(lesson_raw, language, "1.1")
    for entry in spine["derived"]:
        if fault == "no_distractors":
            entry["distractors"] = []
        else:
            for n, item in enumerate(entry["distractors"]):
                item["misconception"] = f"m_never_declared_{entry['ref']}_{n}"
    model = FakeClaude(spine)
    generation = await StoryFromLessonService(model).generate_document(
        chapter_ctx(lesson_raw, language, unit), system_prompt="system"
    )
    assert SENTINEL in model.messages[0]  # shown to the model, as prompt input only
    assert SENTINEL not in json.dumps(generation.doc, ensure_ascii=False)
    if fault == "no_distractors":
        # Left to the repair loop, as for a quiz without option_misconceptions.
        assert generation.model_calls == 1 + MAX_REPAIR_CALLS
        assert "distractor_without_misconception" in model.messages[-1]
    else:
        # Declared from the wrong option itself: the chapter publishes at once.
        assert generation.model_calls == 1 and generation.report.ok

    sources = chapter_sources(fixture, language)
    assert sources[0].unit.unit_number == "1.1"
    ready = generation.doc if generation.report.ok else None
    sources[0] = ChapterSource(sources[0].unit, ready)
    doc = assemble_module_story(module_ctx(fixture, language), sources)
    assert doc["chapters"][0]["covers"]["status"] == ("ready" if ready else "unavailable")
    assert SENTINEL not in json.dumps(doc, ensure_ascii=False)
    assert validate_module_story(doc).ok
