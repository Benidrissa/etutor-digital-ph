"""Contract C-1: a lesson story is one chapter of its module's story.

The module assembler (:mod:`app.domain.services.story_module_assembly`) joins
cached lesson stories without a model call, so every chapter must give it the
same things: the course bible's cast and places (never names the model
writes), no line of the application's own (the screenplay is the model's,
#2674), ``derived_from`` on every question copied from a quiz, and what it was
built with: the generator version in ``sira_builder`` and the bible and the
chapter's part in the mission in ``sira_chapter``.
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.ai.prompts.story_from_lesson import build_story_user_message
from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import default_bible, doc_cast, doc_places
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_from_lesson_service import (
    StoryFromLessonService,
    chapter_marker_matches,
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


def renumber_refs(value: Any) -> Any:
    """The fixture's quiz refs q1..q4 as the covering quiz numbers them, q2..q5."""
    if isinstance(value, dict):
        out = {k: renumber_refs(v) for k, v in value.items()}
        for key in ("ref",):
            ref = out.get(key)
            if isinstance(ref, str) and ref[:1] == "q" and ref[1:].isdigit():
                out[key] = f"q{int(ref[1:]) + 1}"
        return out
    if isinstance(value, list):
        return [renumber_refs(v) for v in value]
    return value


def picking_spine(raw: dict[str, Any], language: str = "en") -> dict[str, Any]:
    """The fixture screenplay with its picks (and asks) renumbered to the covering quiz."""
    return renumber_refs(copy.deepcopy(raw[language]["spine"]))


def all_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for c in doc["chapters"] for s in c["scenes"] for step in s["steps"]]


class FakeClaude:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        response = self.responses[min(len(self.messages), len(self.responses)) - 1]
        return copy.deepcopy(response)


# --------------------------------------------------------------------------
# The course bible's cast and places
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("is_kids", [True, False])
def test_the_cast_is_the_bibles_and_never_comes_from_the_answer(raw, language, is_kids):
    bible = default_bible(is_kids)
    ctx = make_ctx(raw, language, is_kids=is_kids, bible=bible.content)
    plain = repair.build_story_document(ctx, copy.deepcopy(raw[language]["spine"])).doc
    spine = copy.deepcopy(raw[language]["spine"])
    spine["characters"] = {"mentor": "Dr Zinsou Diallo", "peer": "Koffi"}
    spine["cast"] = [{"id": "mentor", "name": "Koffi"}]
    named = repair.build_story_document(ctx, spine).doc

    assert json.dumps(named, ensure_ascii=False) == json.dumps(plain, ensure_ascii=False)
    assert named["cast"] == doc_cast(bible.content)
    assert named["places"] == doc_places(bible.content)
    text = json.dumps(named["cast"], ensure_ascii=False)
    assert "Koffi" not in text and "Diallo" not in text


def test_the_cast_carries_the_contract_fields(raw):
    doc = repair.build_story_document(make_ctx(raw), copy.deepcopy(raw["en"]["spine"])).doc
    by_id = {member["id"]: member for member in doc["cast"]}
    assert list(by_id) == ["hero", "friend", "mentor", "family", "margo"]
    assert by_id["hero"]["name"] == "{child}"
    assert [v["id"] for v in by_id["hero"]["variants"]] == ["woman", "man"]
    assert by_id["friend"]["name"] == "{friend}" and by_id["friend"]["default_name"]
    assert by_id["margo"]["kind"] == "ai_tutor" and by_id["margo"]["role"] == "tutor"
    for member in doc["cast"]:
        assert member["role"] and member["look"] and set(member["voice"]) == {"pitch", "rate"}
        assert "about" not in member


@pytest.mark.parametrize("value", [None, "Koffi", ["Koffi"], {"mentor": 7}])
def test_a_characters_key_of_any_shape_is_ignored(raw, value):
    spine = copy.deepcopy(raw["en"]["spine"])
    spine["characters"] = value
    doc = repair.build_story_document(make_ctx(raw), spine).doc
    assert doc["cast"] == doc_cast(default_bible(False).content)


# --------------------------------------------------------------------------
# The prompt
# --------------------------------------------------------------------------


@pytest.mark.parametrize("is_kids", [True, False])
def test_the_prompt_lists_the_bibles_cast_and_places(raw, is_kids):
    bible = default_bible(is_kids)
    message = build_story_user_message(make_ctx(raw, is_kids=is_kids, bible=bible.content))
    for member in bible.content["cast"]:
        assert f'- "{member["id"]}"' in message
    for place in bible.content["places"]:
        assert f'- "{place["id"]}"' in message
    assert '"characters"' not in message
    # Code-owned: the bible sits before the JSON contract, in the user message.
    assert message.index("=== THE COURSE BIBLE") < message.index("=== OUTPUT ===")


@pytest.mark.parametrize(
    ("arc", "phrase"),
    [
        (repair.ARC_OPENS, "FIRST chapter"),
        (repair.ARC_CONTINUES, "MIDDLE chapter"),
        (repair.ARC_CLOSES, "LAST chapter"),
        (repair.ARC_OPENS_CLOSES, "only this chapter"),
    ],
)
def test_the_prompt_gives_the_mission_and_the_chapters_part_in_it(raw, arc, phrase):
    mission = {"en": "Win the district prize", "fr": "Gagner le prix du district"}
    message = build_story_user_message(make_ctx(raw, arc=arc, mission=mission))
    assert "Win the district prize" in message and "Gagner le prix du district" in message
    assert phrase in message


def test_the_prompt_says_the_lesson_is_one_chapter_of_the_module(raw):
    message = build_story_user_message(make_ctx(raw))
    assert "one chapter (one episode) of the module's story" in message
    assert "CONCEPT 3:" in message and '"teaches"' in message


# --------------------------------------------------------------------------
# No line of the application's own
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
def test_every_story_line_is_the_answers_own(raw, case):
    doc = CASES[case](raw)
    written = {
        (step.get("en"), step.get("fr"))
        for scene in raw["en"]["spine"]["scenes"] + raw["fr"]["spine"]["scenes"]
        for step in scene["steps"]
        if step["type"] in ("narrate", "say")
    }
    for step in all_steps(doc):
        assert "frame" not in step
        if step["type"] in ("narrate", "say"):
            assert (step["en"], step["fr"]) in written


@pytest.mark.parametrize("language", ["en", "fr"])
def test_a_chapter_survives_validation_and_a_round_trip(raw, language):
    doc = CASES[f"fixture-{language}"](raw)
    report = validate_document(doc)
    assert report.ok and report.warnings == [], [i.model_dump() for i in report.warnings]
    dumped = StoryCourse.model_validate(copy.deepcopy(doc)).model_dump(by_alias=True)
    assert dumped["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    assert dumped["sira_chapter"] == doc["sira_chapter"]
    assert dumped["chapters"][0]["scenes"][0]["cast"] == ["mentor", "hero"]


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


def test_a_question_names_its_own_quiz_unit_when_a_story_draws_on_several(raw):
    ctx = covering_ctx(raw)
    for mcq in ctx.mcqs:
        mcq.quiz_unit = "1.9" if mcq.ref == "q3" else "1.3"
    build = repair.build_story_document(ctx, picking_spine(raw))
    units = {
        q["id"]: q["derived_from"]["quiz_unit"]
        for q in build.doc["questions"]
        if "derived_from" in q
    }
    assert units == {"q2": "1.3", "q3": "1.9", "q4": "1.3", "q5": "1.3"}
    assert {s["ref"] for s in build.doc["sources"] if s["kind"] == "test"} == {
        "Unit 1.3 quiz",
        "Unit 1.9 quiz",
    }


def test_no_quiz_means_no_derived_from(raw):
    doc = CASES["no-quiz"](raw)
    assert doc["questions"] and all("derived_from" not in q for q in doc["questions"])


# --------------------------------------------------------------------------
# sira_builder, sira_chapter and determinism
# --------------------------------------------------------------------------


def test_builder_version_is_four():
    assert repair.CHAPTER_BUILDER_VERSION == 4


@pytest.mark.parametrize("case", sorted(CASES))
def test_every_build_records_the_builder_and_its_bible(raw, case):
    doc = CASES[case](raw)
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    assert doc["sira_chapter"]["kind"] == "lesson"
    assert doc["sira_chapter"]["bible"] == default_bible(case == "kids").digest


def test_the_marker_says_which_bible_and_arc(raw):
    bible = default_bible(True)
    ctx = make_ctx(raw, is_kids=True, bible=bible.content, arc=repair.ARC_OPENS)
    marker = repair.build_story_document(ctx, copy.deepcopy(raw["en"]["spine"])).doc["sira_chapter"]
    assert marker == {"kind": "lesson", "bible": bible.digest, "arc": "opens"}
    assert chapter_marker_matches(marker, bible.digest, "opens")
    assert chapter_marker_matches(marker, bible.digest, None)
    assert not chapter_marker_matches(marker, bible.digest, "closes")
    assert not chapter_marker_matches(marker, default_bible(False).digest, "opens")
    assert not chapter_marker_matches(marker, None, "opens")
    assert not chapter_marker_matches(None, bible.digest, "opens")


def test_the_minimal_document_records_the_builder(raw):
    doc = repair.minimal_document(make_ctx(raw))
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    assert doc["sira_chapter"]["kind"] == "lesson"
    StoryCourse.model_validate(doc)


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_generated_chapter_keeps_the_contract(raw, language):
    ctx = covering_ctx(raw, language)
    generation = await StoryFromLessonService(
        FakeClaude(picking_spine(raw, language))
    ).generate_document(ctx, system_prompt="system")
    doc = generation.doc
    assert generation.report.ok and generation.report.warnings == [], [
        i.model_dump() for i in generation.report.errors + generation.report.warnings
    ]
    assert doc["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
    assert doc["cast"] == doc_cast(default_bible(False).content)
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
