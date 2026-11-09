"""A whole kids module told as a screenplay, by one course bible (#2674).

``fixtures/story_screenplay_module.json`` holds a kids biology module set in
Ouagadougou — lessons 1.1, 1.2 and 1.3, the case study 1.4 and the quiz unit
1.5 — with the model's answers: the course bible, the three lessons'
screenplays and the rally's. Its quiz is bilingual, so the same module is told
with French and with English as the language of instruction; the derived
entries (the home-language side of each picked quiz question) are built from
it here, as the model would write them.

The answers run through the real pipeline (normalised bible, chapter
generation with its validation, the rally context, the module assembler and
its validator) with a fake model, and the module story must meet every rule
of the screenplay: no filler chapter, the bible's cast and places, speakers,
moods and places from the bible, no "Name:" label, lines within their limits,
a question right after each concept card and never more than 3 in a row,
every lesson concept taught, no line told twice, the mission set in the first
chapter and solved in the rally, the quiz verbatim and its
``option_misconceptions`` never in the story.
"""

from __future__ import annotations

import copy
import json
import re
import uuid
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.prompts.story_from_lesson import build_story_user_message
from app.api.v1.schemas.story_course import MOODS, StoryCourse
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import (
    BibleModule,
    StoryBible,
    doc_cast,
    doc_places,
    mission_of,
    normalise_bible,
)
from app.domain.services.story_course_validator import line_key, validate_story_course
from app.domain.services.story_from_lesson_service import StoryFromLessonService
from app.domain.services.story_module_assembly import (
    ChapterSource,
    ModuleStoryContext,
    StoryUnit,
    assemble_module_story,
    unit_role,
    validate_module_story,
)
from app.domain.services.story_module_service import mission_arcs, rally_context

FIXTURE = Path(__file__).parent / "fixtures" / "story_screenplay_module.json"
LANGUAGES = ("fr", "en")
SENTINEL = "SENTINEL-OPTION-MISCONCEPTION"


@cache
def data() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def other(language: str) -> str:
    return "en" if language == "fr" else "fr"


class FakeClaude:
    """The model: answers each call with the queued answer, records every message."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        return copy.deepcopy(self.answers[min(len(self.messages), len(self.answers)) - 1])


# --------------------------------------------------------------------------
# The fixture, as the pipeline sees it
# --------------------------------------------------------------------------


def story_units() -> list[StoryUnit]:
    return [
        StoryUnit(
            module_unit_id=uuid.UUID(unit["module_unit_id"]),
            unit_number=unit["unit_number"],
            unit_type=unit["unit_type"],
            order_index=unit["order_index"],
            role=unit_role(unit["unit_type"]),
            title=dict(unit["title"]),
        )
        for unit in data()["units"]
    ]


def bible() -> StoryBible:
    module = data()["module"]
    modules = [BibleModule(uuid.UUID(module["module_id"]), 1, module["module_title"])]
    content = normalise_bible(data()["bible"], is_kids=True, modules=modules, country="BF")
    return StoryBible.of(content)


def quiz_questions(language: str) -> list[dict[str, Any]]:
    """Unit 1.5's quiz in ``language``; every option_misconceptions slot is a sentinel."""
    out = []
    for q in data()["quiz"]:
        out.append(
            {
                "id": q["id"],
                "question": q["question"][language],
                "options": list(q["options"][language]),
                "correct_answer": q["correct_answer"],
                "explanation": q["explanation"][language],
                "option_misconceptions": [
                    None if i == q["correct_answer"] else f"{SENTINEL}-{q['id']}-{i}"
                    for i in range(len(q["options"][language]))
                ],
            }
        )
    return out


def quiz_row(language: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=15), content_revision=1, content={"questions": quiz_questions(language)}
    )


def _derived(quiz_id: str, ref: str, objective: str, language: str) -> dict[str, Any]:
    """The model's ``derived`` entry for a picked quiz question: its home side."""
    q = next(q for q in data()["quiz"] if q["id"] == quiz_id)
    home = other(language)
    return {
        "ref": ref,
        "objective": objective,
        "prompt_home": q["question"][home],
        "options_home": list(q["options"][home]),
        "explanation_home": q["explanation"][home],
        "hint": q["hint"],
        "distractors": [
            {"option": d["option"], "misconception": d["misconception"]["id"], "hint": d["hint"]}
            for d in q["distractors"]
        ],
    }


def _spine(source: dict[str, Any], language: str, refs: dict[str, str]) -> dict[str, Any]:
    """A screenplay answer of the model, its quiz refs as the prompt numbered them."""
    source = copy.deepcopy(source)
    misconceptions: dict[str, dict[str, str]] = {}
    derived = []
    for quiz_id, objective in source["picks"]:
        entry = _derived(quiz_id, refs[quiz_id], objective, language)
        derived.append(entry)
        q = next(q for q in data()["quiz"] if q["id"] == quiz_id)
        for d in q["distractors"]:
            misconceptions.setdefault(d["misconception"]["id"], d["misconception"])
    for item in [*source["misconceptions"], *source["extra_misconceptions_for_game"]]:
        misconceptions.setdefault(item["id"], item)
    scenes = source["scenes"]
    for scene in scenes:
        for step in scene["steps"]:
            if step["type"] == "ask" and step["ref"] in refs:
                step["ref"] = refs[step["ref"]]
    spine: dict[str, Any] = {
        "objectives": source["objectives"],
        "misconceptions": list(misconceptions.values()),
        "scenes": scenes,
        "derived": derived,
        "questions": source["questions"],
        "exercises": source["exercises"],
        "minigame": source["minigame"],
        "facts": source["facts"],
        "__complete": True,
    }
    if "chapter_title" in source:
        spine["chapter_title"] = source["chapter_title"]
    return spine


def lesson_ctx(unit: StoryUnit, language: str) -> repair.LessonStoryContext:
    lesson = data()["lessons"][unit.unit_number]["lesson"]
    mcqs, dropped = repair.parse_quiz_mcqs(quiz_questions(language))
    assert dropped == []
    the_bible = bible()
    module = data()["module"]
    return repair.LessonStoryContext(
        module_unit_id=unit.module_unit_id,
        language=language,
        unit_number=unit.unit_number,
        unit_title=dict(unit.title),
        module_title=dict(module["module_title"]),
        course_title=dict(module["course_title"]),
        module_number=1,
        lesson={
            "introduction": lesson["introduction"][language],
            "concepts": lesson["concepts"][language],
            "key_points": lesson["key_points"][language],
        },
        mcqs=mcqs,
        has_quiz=True,
        is_kids=True,
        quiz_scope="covering",
        quiz_unit_number="1.5",
        bible=the_bible.content,
        mission=mission_of(the_bible.content, module["module_id"]),
        arc=mission_arcs(story_units())[unit.module_unit_id],
        country="BF",
    )


def lesson_spine(unit_number: str, language: str) -> dict[str, Any]:
    refs = {q["id"]: q["id"] for q in data()["quiz"]}  # the covering quiz keeps its order
    return _spine(data()["lessons"][unit_number], language, refs)


def module_ctx(language: str) -> ModuleStoryContext:
    module = data()["module"]
    return ModuleStoryContext(
        module_id=uuid.UUID(module["module_id"]),
        language=language,
        module_number=module["module_number"],
        module_title=dict(module["module_title"]),
        course_title=dict(module["course_title"]),
        previous_module=None,
        is_kids=True,
        bible=bible(),
    )


async def tell(language: str) -> dict[str, Any]:
    """The whole module story in ``language``: chapters, rally, assembly — and the trail."""
    chapters: dict[str, dict[str, Any]] = {}
    messages: dict[str, str] = {}
    for unit in story_units():
        if unit.role != "lesson":
            continue
        model = FakeClaude(lesson_spine(unit.unit_number, language))
        generation = await StoryFromLessonService(model).generate_document(
            lesson_ctx(unit, language), system_prompt="system"
        )
        assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
        assert generation.report.warnings == [], [
            w.model_dump() for w in generation.report.warnings
        ]
        assert generation.model_calls == 1
        chapters[unit.unit_number] = generation.doc
        messages[unit.unit_number] = model.messages[0]

    units = story_units()
    sources = [ChapterSource(unit=u, doc=chapters.get(u.unit_number)) for u in units]
    quiz_units = [u for u in units if u.role == "quiz_checkpoint"]
    ctx = module_ctx(language)
    rally_ctx, inputs = rally_context(
        ctx, sources, quiz_units, [(quiz_units[0], quiz_row(language))], country="BF"
    )
    assert rally_ctx is not None
    refs = {mcq.source_id: mcq.ref for mcq in rally_ctx.mcqs}
    model = FakeClaude(_spine(data()["rally"], language, refs))
    generation = await StoryFromLessonService(model, max_repair_calls=1).generate_document(
        rally_ctx, system_prompt="system"
    )
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    rally = generation.doc
    messages["rally"] = model.messages[0]

    doc = assemble_module_story(ctx, sources, rally)
    return {
        "doc": doc,
        "chapters": chapters,
        "rally": rally,
        "rally_ctx": rally_ctx,
        "inputs": inputs,
        "messages": messages,
        "sources": sources,
    }


@pytest.fixture(scope="module", params=LANGUAGES)
async def told(request) -> dict[str, Any]:
    return {"language": request.param, **(await tell(request.param))}


def chapter_steps(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for scene in chapter["scenes"] for step in scene["steps"]]


# --------------------------------------------------------------------------
# The course bible
# --------------------------------------------------------------------------


def test_the_bible_answer_is_normalised_to_the_contract():
    content = bible().content
    assert content["audience"] == "kids" and content["country"] == "BF"
    cast = {member["id"]: member for member in content["cast"]}
    assert list(cast) == ["hero", "friend", "mentor", "family", "margo"]
    assert cast["hero"]["name"] == "{child}" and cast["hero"]["kind"] == "child"
    assert [v["id"] for v in cast["hero"]["variants"]] == ["girl", "boy"]
    assert all("Burkinabe" in v["look"] for v in cast["hero"]["variants"])
    assert cast["friend"]["name"] == "{friend}" and cast["friend"]["default_name"] == "Awa"
    # Names read the same in English and French: no "Mr" / "M.".
    assert cast["mentor"]["name"] == "Kaboré"
    assert cast["margo"]["kind"] == "ai_tutor" and cast["margo"]["role"] == "tutor"
    assert [m["role"] for m in content["cast"]] == ["hero", "friend", "mentor", "family", "tutor"]
    for member in content["cast"]:
        assert member["look"] and not member["look"].endswith(".")
        assert 0.5 <= member["voice"]["pitch"] <= 2 and 0.7 <= member["voice"]["rate"] <= 1.3
    assert [p["id"] for p in content["places"]] == [
        "rood_woko_market",
        "courtyard",
        "classroom",
        "school_garden",
        "science_fair",
        "tanghin_dam",
    ]
    assert all(set(p["title"]) == {"en", "fr"} and p["look"] for p in content["places"])
    assert all(f.get("source") or f["invented"] for f in content["facts"])
    assert [f["invented"] for f in content["facts"]] == [False, False, False, True]
    mission = content["missions"][data()["module"]["module_id"]]
    assert "basket" in mission["en"] and "panier" in mission["fr"]


def test_the_bible_is_identical_in_every_module_story_of_the_course():
    first = assemble_module_story(module_ctx("fr"), [])
    second = assemble_module_story(module_ctx("en"), [])
    assert first["cast"] == second["cast"] == doc_cast(bible().content)
    assert first["places"] == second["places"] == doc_places(bible().content)
    assert first["module_story"]["bible"] == second["module_story"]["bible"] == bible().digest


# --------------------------------------------------------------------------
# The module story
# --------------------------------------------------------------------------


async def test_the_module_story_validates_with_zero_errors_and_zero_warnings(told):
    doc = told["doc"]
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    assert report.warnings == [], [w.model_dump() for w in report.warnings]
    direct = validate_story_course(StoryCourse.model_validate(json.loads(json.dumps(doc))))
    assert direct.ok and direct.warnings == []


async def test_one_chapter_per_lesson_then_the_rally_and_no_filler(told):
    chapters = told["doc"]["chapters"]
    covers = [c["covers"] for c in chapters]
    assert [c["unit_number"] for c in covers] == ["1.1", "1.2", "1.3", "1.5"]
    for cover in covers[:3]:
        assert cover["role"] == "lesson" and cover["status"] == "ready"
        assert cover["completes_unit"] is True and cover["max_points"] > 0
    rally = covers[3]
    assert rally["role"] == "quiz_checkpoint" and rally["status"] == "checkpoint"
    assert rally["rally"] is True and rally["completes_unit"] is False
    assert rally["max_points"] > 0
    assert chapters[3]["title"] == data()["rally"]["chapter_title"]
    # The case study 1.4 has no chapter, and no line sends anyone to a page.
    text = json.dumps([c["scenes"] for c in chapters], ensure_ascii=False).lower()
    for meta in ("on its page", "sur sa page", "this story", "cette histoire", "checkpoint"):
        assert meta not in text
    assert all("frame" not in step for c in chapters for step in chapter_steps(c))


async def test_the_cast_and_places_are_the_bibles(told):
    doc = told["doc"]
    assert doc["cast"] == doc_cast(bible().content)
    assert doc["places"] == doc_places(bible().content)
    place_ids = {p["id"] for p in doc["places"]}
    cast_ids = {c["id"] for c in doc["cast"]}
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            assert scene["place"] in place_ids
            assert 2 <= len(scene["cast"]) <= 3 and set(scene["cast"]) <= cast_ids
            for step in scene["steps"]:
                if step["type"] == "say":
                    assert step["who"] in scene["cast"] and step["mood"] in MOODS


async def test_every_line_is_dialogue_or_narration_within_its_limits(told):
    doc = told["doc"]
    names = re.compile(
        r"^(?:mr|m\.|mme)?\s*(kaboré|mariam|margo|\{friend\}|\{child\})\s*(:|says|dit)", re.I
    )
    lines = [
        s for c in doc["chapters"] for s in chapter_steps(c) if s["type"] in ("narrate", "say")
    ]
    for step in lines:
        assert len(step["en"]) <= 100 and len(step["fr"]) <= 118, step
        if step["type"] == "say":
            assert not names.match(step["en"]) and not names.match(step["fr"]), step
    # The hero speaks, in the first person; the friend is the learner's own.
    hero = [s for s in lines if s.get("who") == "hero"]
    assert len(hero) >= 8
    assert any(re.search(r"\b(I|my|me)\b", s["en"]) for s in hero)
    assert any("{friend}" in s["en"] for s in lines)
    # Margo says she is an AI the first time she speaks.
    margo = [s for s in lines if s.get("who") == "margo"]
    assert margo and "AI" in margo[0]["en"] and "IA" in margo[0]["fr"]


async def test_no_line_is_told_twice(told):
    seen: dict[tuple[str, str], str] = {}
    for chapter in told["doc"]["chapters"]:
        for step in chapter_steps(chapter):
            if step["type"] in ("narrate", "say"):
                for lang in ("en", "fr"):
                    key = (lang, line_key(step[lang]))
                    assert seen.setdefault(key, chapter["id"]) == chapter["id"], step


async def test_each_concept_card_is_followed_by_its_questions(told):
    for chapter in told["doc"]["chapters"]:
        steps = chapter_steps(chapter)
        run = 0
        for step in steps:
            run = run + 1 if step["type"] == "ask" else 0
            assert run <= 3
        cards = [
            i
            for i, s in enumerate(steps)
            if s["type"] == "concept" and not s["id"].endswith(tuple(f"situation-{x}" for x in "q"))
        ]
        for index in cards:
            following = steps[index + 1 :]
            if not following:
                continue
            asks = 0
            for step in following:
                if step["type"] == "ask":
                    asks += 1
                elif step["type"] == "concept" and "situation-" in step["id"]:
                    continue
                else:
                    break
            assert 1 <= asks <= 3, (chapter["id"], steps[index]["id"])


async def test_every_lesson_concept_is_taught(told):
    for chapter in told["doc"]["chapters"][:3]:
        taught = sorted(s["teaches"] for s in chapter_steps(chapter) if "teaches" in s)
        assert taught == [1, 2, 3], chapter["id"]
        assert len(chapter["scenes"]) == 3
    assert 2 <= len(told["doc"]["chapters"][3]["scenes"]) <= 3


async def test_the_mission_is_set_first_and_solved_in_the_rally(told):
    messages = told["messages"]
    mission = bible().content["missions"][data()["module"]["module_id"]]
    for key in ("1.1", "1.2", "1.3", "rally"):
        assert mission["en"] in messages[key]
    assert "FIRST chapter" in messages["1.1"]
    assert "MIDDLE chapter" in messages["1.2"] and "MIDDLE chapter" in messages["1.3"]
    assert "LAST chapter" in messages["rally"]
    assert [told["chapters"][n]["sira_chapter"]["arc"] for n in ("1.1", "1.2", "1.3")] == [
        "opens",
        "continues",
        "continues",
    ]
    assert told["rally"]["sira_chapter"] == {
        "kind": "rally",
        "bible": bible().digest,
        "arc": "closes",
    }
    first = " ".join(
        s["en"]
        for s in chapter_steps(told["doc"]["chapters"][0])
        if "en" in s and isinstance(s["en"], str)
    )
    last = " ".join(
        s["en"] for s in chapter_steps(told["doc"]["chapters"][-1]) if isinstance(s.get("en"), str)
    )
    assert "science fair" in first and "basket" in first
    assert "solved" in last and "ribbon" in last


async def test_the_quiz_is_verbatim_and_its_misconceptions_never_reach_the_story(told):
    language = told["language"]
    doc = told["doc"]
    text = json.dumps(doc, ensure_ascii=False)
    assert SENTINEL not in text and "option_misconceptions" not in text
    stored = {q["id"]: q for q in quiz_questions(language)}
    derived = [q for q in doc["questions"] if q.get("derived_from")]
    assert len(derived) == 13  # 3 per lesson, 4 in the rally (one a review)
    for question in derived:
        source = stored[question["derived_from"]["question_id"]]
        assert question["derived_from"]["quiz_unit"] == "1.5"
        assert [c[language] for c in question["choices"]] == source["options"]
        assert question["answer"] == "abcd"[source["correct_answer"]]
        shown = question.get("stem", question["prompt"])[language]
        assert shown == source["question"]
        correct = next(c for c in question["choices"] if c["id"] == question["answer"])
        assert "misconception" not in correct
        assert all(c.get("misconception") for c in question["choices"] if c is not correct)


async def test_the_rally_mixes_the_questions_no_lesson_asked(told):
    rally_ctx = told["rally_ctx"]
    by_source = {m.source_id: m for m in rally_ctx.mcqs}
    assert [m.source_id for m in rally_ctx.mcqs][:3] == ["q10", "q11", "q12"]
    assert all(not by_source[q].asked_before for q in ("q10", "q11", "q12"))
    assert all(by_source[f"q{n}"].asked_before for n in range(1, 10))
    assert "(already asked)" in told["messages"]["rally"]
    asked = [
        q["derived_from"]["question_id"]
        for q in told["rally"]["questions"]
        if q.get("derived_from")
    ]
    # In candidate order: the three no lesson asked, then the review.
    assert asked == ["q10", "q11", "q12", "q8"]
    assert "RALLY" in told["messages"]["rally"]


async def test_facts_carry_a_source_or_say_they_are_invented(told):
    facts = told["doc"]["facts"]
    assert facts and all(f.get("source") or f.get("invented") for f in facts)
    assert any(f.get("invented") for f in facts)


def test_the_prompt_of_a_lesson_carries_the_bible_and_the_contract():
    unit = story_units()[0]
    message = build_story_user_message(lesson_ctx(unit, "fr"))
    assert '"rood_woko_market"' in message and '"margo"' in message
    assert "Kaboré" in message and "Mr Kaboré" not in message
    assert "CONCEPT 3:" in message and '"teaches"' in message
    assert "at most 100 characters in English and 118 in French" in message


async def test_the_rally_inputs_change_with_what_the_lessons_asked():
    language = "fr"
    result = await tell(language)
    units = story_units()
    quiz_units = [u for u in units if u.role == "quiz_checkpoint"]
    ctx = module_ctx(language)
    _same, again = rally_context(
        ctx, result["sources"], quiz_units, [(quiz_units[0], quiz_row(language))]
    )
    assert again == result["inputs"]
    fewer = [
        s if s.unit.unit_number != "1.3" else ChapterSource(s.unit, None) for s in result["sources"]
    ]
    rally_ctx, changed = rally_context(
        ctx, fewer, quiz_units, [(quiz_units[0], quiz_row(language))]
    )
    assert changed != result["inputs"]
    assert rally_ctx is not None and not by_id(rally_ctx, "q8").asked_before
    none, _ = rally_context(ctx, result["sources"], quiz_units, [])
    assert none is None


def by_id(ctx: repair.LessonStoryContext, quiz_id: str) -> repair.QuizMcq:
    return next(m for m in ctx.mcqs if m.source_id == quiz_id)
