"""Contract C-1: a lesson story is one chapter of its module's story.

The module assembler (:mod:`app.domain.services.story_module_assembly`) joins
cached lesson stories without a model call, so every chapter must give it the
same things: one pinned cast, a ``frame`` marker on each deterministic frame
step (it edits by marker, never by text), ``derived_from`` on every question
copied from a quiz, and the builder version in ``sira_builder``.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.ai.prompts.story_from_lesson import CHAPTER_LINE, build_story_user_message
from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    StoryFromLessonService,
    validate_document,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_story_unit.json"
UNIT_ID = uuid.UUID("2f1e0d3c-4b5a-4968-8776-655443322110")

#: The covering quiz unit's quiz: one other lesson's MCQ, the fixture's four,
#: another one (the fixture's ids q1..q4 become candidate refs q2..q5).
OTHER = {
    "en": [
        {
            "id": "tb1",
            "question": "How long does standard tuberculosis treatment last?",
            "options": ["Two weeks", "Six months", "Ten years", "One day"],
            "correct_answer": 1,
        },
        {
            "id": "wash1",
            "question": "When should hands be washed with soap?",
            "options": ["Only on Sundays", "Before eating", "Never", "Once a year"],
            "correct_answer": 1,
        },
    ],
    "fr": [
        {
            "id": "tb1",
            "question": "Combien de temps dure le traitement standard de la tuberculose ?",
            "options": ["Deux semaines", "Six mois", "Dix ans", "Un jour"],
            "correct_answer": 1,
        },
        {
            "id": "wash1",
            "question": "Quand faut-il se laver les mains au savon ?",
            "options": ["Le dimanche", "Avant de manger", "Jamais", "Une fois par an"],
            "correct_answer": 1,
        },
    ],
}

FRAME_TEXT = {
    "opener": ("narrate", None, "This story is about you, {child}."),
    "objectives": ("concept", None, "What you will learn"),
    "finished": ("narrate", None, "Well done, {child}: you have finished this story."),
    "ask_tutor": ("say", "margo", "Questions about this lesson? Ask me any time, {child}."),
}


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_ctx(raw: dict[str, Any], language: str = "en", **overrides: Any):
    data = raw[language]
    mcqs, _ = repair.parse_quiz_mcqs(copy.deepcopy(data["quiz"]["questions"]))
    values: dict[str, Any] = {
        "module_unit_id": UNIT_ID,
        "language": language,
        "unit_number": "1.2",
        "unit_title": {"en": "Preventing malaria in children", "fr": "Prévenir le paludisme"},
        "module_title": {"en": "Malaria control", "fr": "Lutte contre le paludisme"},
        "course_title": {"en": "Public health", "fr": "Santé publique"},
        "module_number": 3,
        "lesson": copy.deepcopy(data["lesson"]),
        "mcqs": mcqs,
        "has_quiz": bool(mcqs),
    }
    values.update(overrides)
    return repair.LessonStoryContext(**values)


def covering_ctx(raw: dict[str, Any], language: str = "en", **overrides: Any):
    questions = [OTHER[language][0], *raw[language]["quiz"]["questions"], OTHER[language][1]]
    mcqs, _ = repair.parse_quiz_mcqs(copy.deepcopy(questions))
    return make_ctx(
        raw,
        language,
        mcqs=mcqs,
        has_quiz=True,
        quiz_scope="covering",
        quiz_unit_number="1.3",
        **overrides,
    )


def picking_spine(raw: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """The fixture spine with its picks renumbered to the covering quiz."""
    spine = copy.deepcopy(raw[language]["spine"])
    for entry in spine["derived"]:
        entry["ref"] = f"q{int(entry['ref'][1:]) + 1}"
    return spine


def all_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for c in doc["chapters"] for s in c["scenes"] for step in s["steps"]]


def framed(doc: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for step in all_steps(doc):
        if "frame" in step:
            out.setdefault(step["frame"], []).append(step)
    return out


class FakeClaude:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        response = self.responses[min(len(self.messages), len(self.responses)) - 1]
        return copy.deepcopy(response)


# --------------------------------------------------------------------------
# The pinned cast
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("is_kids", "language", "mentor", "peer"),
    [
        (True, "fr", "M. Kaboré", {"kind": "child", "art": "friend"}),
        (True, "en", "Mr Kaboré", {"kind": "child", "art": "friend"}),
        (False, "fr", "Dr Kaboré", {"kind": "adult", "art": "maman_olivia"}),
        (False, "en", "Dr Kaboré", {"kind": "adult", "art": "maman_olivia"}),
    ],
)
def test_pinned_cast_is_exactly_the_contract(is_kids, language, mentor, peer):
    assert repair.pinned_cast(is_kids, language) == [
        {"id": "margo", "name": "Margo", "kind": "ai_tutor", "art": "margo"},
        {"id": "mentor", "name": mentor, "kind": "adult", "art": "mr_kabore"},
        {"id": "peer", "name": "Awa", **peer},
    ]


def test_pinned_cast_returns_fresh_dicts():
    first = repair.pinned_cast(True, "fr")
    first[1]["name"] = "Someone else"
    assert repair.pinned_cast(True, "fr")[1]["name"] == "M. Kaboré"


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("is_kids", [True, False])
def test_cast_names_never_come_from_the_spine(raw, language, is_kids):
    ctx = make_ctx(raw, language, is_kids=is_kids)
    plain = repair.build_story_document(ctx, copy.deepcopy(raw[language]["spine"])).doc
    spine = copy.deepcopy(raw[language]["spine"])
    spine["characters"] = {"mentor": "Dr Zinsou Diallo", "peer": "Koffi"}
    named = repair.build_story_document(ctx, spine).doc

    assert json.dumps(named, ensure_ascii=False) == json.dumps(plain, ensure_ascii=False)
    assert named["cast"] == repair.pinned_cast(is_kids, language)
    text = json.dumps(named["cast"], ensure_ascii=False)
    assert "Koffi" not in text and "Diallo" not in text


@pytest.mark.parametrize("value", [None, "Koffi", ["Koffi"], {"mentor": 7}])
def test_a_characters_key_of_any_shape_is_ignored(raw, value):
    spine = copy.deepcopy(raw["en"]["spine"])
    spine["characters"] = value
    doc = repair.build_story_document(make_ctx(raw), spine).doc
    assert doc["cast"] == repair.pinned_cast(False, "en")


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("is_kids", "language", "mentor"),
    [(True, "fr", "M. Kaboré"), (True, "en", "Mr Kaboré"), (False, "en", "Dr Kaboré")],
)
def test_the_prompt_names_the_cast_and_asks_for_no_names(raw, is_kids, language, mentor):
    message = build_story_user_message(make_ctx(raw, language, is_kids=is_kids))
    assert '"characters"' not in message
    assert f"the mentor is {mentor}, the peer is Awa and the AI tutor is Margo" in message


def test_the_prompt_says_the_lesson_is_one_chapter_of_the_module(raw):
    message = build_story_user_message(make_ctx(raw))
    assert CHAPTER_LINE in message
    assert "one chapter of the module's story" in CHAPTER_LINE
    assert '"story.wrap_up" closes only this lesson\'s part' in CHAPTER_LINE
    # Code-owned: it sits before the JSON contract, in the user message.
    assert message.index(CHAPTER_LINE) < message.index("=== OUTPUT ===")


# --------------------------------------------------------------------------
# Frame markers
# --------------------------------------------------------------------------


def _salvage_rebuild(raw: dict[str, Any]) -> dict[str, Any]:
    """A rebuild without some items, as the salvage pass makes it."""
    return repair.build_story_document(
        make_ctx(raw),
        copy.deepcopy(raw["en"]["spine"]),
        drop_question_ids={"q2", "x1"},
        drop_exercise_ids={"E1"},
        drop_minigame=True,
    ).doc


CASES = {
    "fixture-en": lambda raw: (
        repair.build_story_document(make_ctx(raw, "en"), copy.deepcopy(raw["en"]["spine"])).doc
    ),
    "fixture-fr": lambda raw: (
        repair.build_story_document(make_ctx(raw, "fr"), copy.deepcopy(raw["fr"]["spine"])).doc
    ),
    "empty-spine": lambda raw: repair.build_story_document(make_ctx(raw), {}).doc,
    "kids": lambda raw: (
        repair.build_story_document(
            make_ctx(raw, "fr", is_kids=True), copy.deepcopy(raw["fr"]["spine"])
        ).doc
    ),
    "covering": lambda raw: repair.build_story_document(covering_ctx(raw), picking_spine(raw)).doc,
    "no-quiz": lambda raw: (
        repair.build_story_document(
            make_ctx(raw, mcqs=[], has_quiz=False), copy.deepcopy(raw["en"]["spine"])
        ).doc
    ),
    "no-lesson-body": lambda raw: (
        repair.build_story_document(make_ctx(raw, lesson={}), copy.deepcopy(raw["en"]["spine"])).doc
    ),
    "salvage": _salvage_rebuild,
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_each_frame_marker_is_on_exactly_one_step(raw, case):
    doc = CASES[case](raw)
    found = framed(doc)
    assert sorted(found) == sorted(repair.FRAMES)
    for marker, (kind, who, english) in FRAME_TEXT.items():
        (step,) = found[marker]
        assert step["type"] == kind
        assert step.get("who") == who
        shown = step["title"]["en"] if kind == "concept" else step["en"]
        assert shown == english


@pytest.mark.parametrize("case", sorted(CASES))
def test_frame_steps_sit_where_the_assembler_expects_them(raw, case):
    doc = CASES[case](raw)
    first_scene = doc["chapters"][0]["scenes"][0]["steps"]
    last_scene = doc["chapters"][-1]["scenes"][-1]["steps"]
    assert first_scene[0]["frame"] == "opener"
    assert [s.get("frame") for s in first_scene].count("objectives") == 1
    assert [s.get("frame") for s in last_scene[-2:]] == ["finished", "ask_tutor"]


def test_the_objectives_step_lists_the_objectives(raw):
    doc = CASES["fixture-fr"](raw)
    (step,) = framed(doc)["objectives"]
    assert step["fr"] == [o["fr"] for o in doc["objectives"]]
    assert step["en"] == [o["en"] for o in doc["objectives"]]


@pytest.mark.parametrize("language", ["en", "fr"])
def test_frame_markers_survive_validation_and_a_round_trip(raw, language):
    doc = CASES[f"fixture-{language}"](raw)
    report = validate_document(doc)
    assert report.ok and report.warnings == [], [i.model_dump() for i in report.warnings]
    dumped = StoryCourse.model_validate(copy.deepcopy(doc)).model_dump(by_alias=True)
    assert sorted(framed(dumped)) == sorted(repair.FRAMES)
    assert dumped["sira_builder"] == repair.CHAPTER_BUILDER_VERSION


# --------------------------------------------------------------------------
# derived_from
# --------------------------------------------------------------------------


def test_derived_from_names_the_covering_quiz_unit(raw):
    build = repair.build_story_document(covering_ctx(raw), picking_spine(raw))
    by_id = {q["id"]: q for q in build.doc["questions"]}
    assert build.derived_ids == ["q2", "q3", "q4", "q5"]
    assert [by_id[i]["derived_from"] for i in build.derived_ids] == [
        {"quiz_unit": "1.3", "question_id": m["id"]} for m in raw["en"]["quiz"]["questions"]
    ]
    assert build.extra_ids and all("derived_from" not in by_id[i] for i in build.extra_ids)


def test_derived_from_of_a_units_own_quiz_names_the_unit(raw):
    build = repair.build_story_document(make_ctx(raw), copy.deepcopy(raw["en"]["spine"]))
    derived = [q for q in build.doc["questions"] if "derived_from" in q]
    assert [q["id"] for q in derived] == build.derived_ids == ["q1", "q2", "q3", "q4"]
    assert {q["derived_from"]["quiz_unit"] for q in derived} == {"1.2"}
    assert [q["derived_from"]["question_id"] for q in derived] == ["q1", "q2", "q3", "q4"]
    assert all("derived_from" not in q for q in build.doc["questions"] if q["id"] == "x1")


def test_no_quiz_means_no_derived_from(raw):
    doc = CASES["no-quiz"](raw)
    assert doc["questions"] and all("derived_from" not in q for q in doc["questions"])


# --------------------------------------------------------------------------
# sira_builder and determinism
# --------------------------------------------------------------------------


def test_builder_version_is_two():
    assert repair.CHAPTER_BUILDER_VERSION == 2


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_build_records_the_builder(raw, case):
    assert CASES[case](raw)["sira_builder"] == repair.CHAPTER_BUILDER_VERSION


def test_the_minimal_document_records_the_builder(raw):
    doc = repair.minimal_document(make_ctx(raw))
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    StoryCourse.model_validate(doc)


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_generated_chapter_keeps_the_contract(raw, language):
    ctx = covering_ctx(raw, language)
    generation = await StoryFromLessonService(
        FakeClaude(picking_spine(raw, language))
    ).generate_document(ctx, system_prompt="system")
    doc = generation.doc
    assert generation.report.ok and generation.report.warnings == []
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    assert sorted(framed(doc)) == sorted(repair.FRAMES)
    assert doc["cast"] == repair.pinned_cast(False, language)
    assert all(
        q["derived_from"]["quiz_unit"] == "1.3" for q in doc["questions"] if "derived_from" in q
    )
    report = validate_story_course(StoryCourse.model_validate(copy.deepcopy(doc)))
    assert report.ok and report.warnings == []


async def test_an_unbuildable_answer_still_records_the_builder(raw):
    generation = await StoryFromLessonService(FakeClaude("not json")).generate_document(
        make_ctx(raw), system_prompt="system"
    )
    assert generation.doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION


@pytest.mark.parametrize("case", sorted(CASES))
def test_the_builder_is_deterministic(raw, case):
    first = json.dumps(CASES[case](raw), ensure_ascii=False, sort_keys=False)
    second = json.dumps(CASES[case](raw), ensure_ascii=False, sort_keys=False)
    assert first == second


# --------------------------------------------------------------------------
# The setting
# --------------------------------------------------------------------------


def test_the_master_switch_is_about_module_stories():
    from app.infrastructure.config.platform_defaults import DEFAULTS_BY_KEY

    flag = DEFAULTS_BY_KEY["story-mode-feature-enabled"]
    assert flag.label == "Module story mode enabled"
    assert flag.description.startswith("Master switch for module story mode.")
    assert "per-lesson" not in flag.description
