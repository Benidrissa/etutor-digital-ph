"""A whole kids module told as ONE episode, from its plan, chapter after chapter (#2680).

``fixtures/story_screenplay_module.json`` holds a kids biology module set in
Ouagadougou — lessons 1.1, 1.2 and 1.3, the case study 1.4 and the quiz unit
1.5 — with its course bible, the practice packs and the story answers of the
model; ``fixtures/story_module_plan.json`` is the showrunner's plan answer.
The quiz is bilingual, so the same module is told with French and with
English as the language of instruction.

The answers run through the real v4 pipeline with a fake model and no
database: the plan is validated and normalised, each chapter's context and
message are built by :class:`ModuleStoryService` exactly as a run builds them
(the plan, the story so far, the previous chapter's real last scene), each
pack and story is built and validated by the chapter builder, then the rally,
then the assembler. The module story must sound like a story: story lines
dominate, every question has a lead-in and a reaction, chapters end on a
story line, every lesson idea is on a card, no line is told twice but a
refrain, every concrete thing a line names is a prop on stage, and the quiz
stays verbatim. And the fixture must be honest: whatever a chapter shares
with another (a prop, a weekday, a name) is in that chapter's built message.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.prompts.story_from_lesson import (
    build_chapter_story_message,
    build_pack_message,
    build_rally_story_message,
    fact_sheet_digest,
)
from app.ai.prompts.story_plan import build_plan_user_message
from app.api.v1.schemas.story_course import MOODS, StoryCourse
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import (
    BibleModule,
    StoryBible,
    doc_cast,
    doc_places,
    normalise_bible,
)
from app.domain.services.story_course_validator import line_key, validate_story_course
from app.domain.services.story_from_lesson_service import StoryFromLessonService, pack_issues
from app.domain.services.story_module_assembly import (
    ChapterSource,
    ModuleStoryContext,
    StoryUnit,
    assemble_module_story,
    unit_role,
    validate_module_story,
)
from app.domain.services.story_module_service import ModuleStoryService, _props_seen, _Run
from app.domain.services.story_plan import (
    EpisodePlan,
    global_digest,
    normalise_plan,
    plan_digest,
    validate_plan,
)

FIXTURES = Path(__file__).parent / "fixtures"
LANGUAGES = ("fr", "en")
SENTINEL = "SENTINEL-OPTION-MISCONCEPTION"
WEEKDAYS = {
    "monday": "lundi",
    "tuesday": "mardi",
    "wednesday": "mercredi",
    "thursday": "jeudi",
    "friday": "vendredi",
    "saturday": "samedi",
    "sunday": "dimanche",
}


@cache
def data() -> dict[str, Any]:
    return json.loads((FIXTURES / "story_screenplay_module.json").read_text(encoding="utf-8"))


@cache
def plan_answer() -> dict[str, Any]:
    return json.loads((FIXTURES / "story_module_plan.json").read_text(encoding="utf-8"))


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
    return [
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
        for q in data()["quiz"]
    ]


def lesson_content(unit_number: str, language: str) -> dict[str, Any]:
    lesson = data()["lessons"][unit_number]["lesson"]
    return {key: value[language] for key, value in lesson.items()}


def pack(key: str, language: str) -> dict[str, Any]:
    """A practice pack of the model: its derived entries are the quiz's home side."""
    source = copy.deepcopy(data()["packs"][key])
    home = other(language)
    misconceptions = {m["id"]: m for m in source["misconceptions"]}
    derived = []
    for ref, idea in source.pop("derived_ideas").items():
        q = next(q for q in data()["quiz"] if q["id"] == ref)
        for d in q["distractors"]:
            misconceptions.setdefault(d["misconception"]["id"], d["misconception"])
        derived.append(
            {
                "ref": ref,
                "idea": idea,
                "objective": "o1",
                "prompt_home": q["question"][home],
                "options_home": list(q["options"][home]),
                "explanation_home": q["explanation"][home],
                "hint": q["hint"],
                "distractors": [
                    {
                        "option": d["option"],
                        "misconception": d["misconception"]["id"],
                        "hint": d["hint"],
                    }
                    for d in q["distractors"]
                ],
            }
        )
    source["misconceptions"] = list(misconceptions.values())
    source["derived"] = derived
    return source


def story_answer(key: str) -> dict[str, Any]:
    return {**copy.deepcopy(data()["stories"][key]), "__complete": True}


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


def make_run(language: str) -> tuple[ModuleStoryService, _Run, ModuleStoryContext]:
    """A run as the module service builds it, its rows from the fixture, its plan normalised."""
    units = story_units()
    service = ModuleStoryService(FakeClaude(), None, None)
    by_number = {u.unit_number: u for u in units}
    quiz_unit = by_number["1.5"]
    run = _Run(
        module_id=uuid.UUID(data()["module"]["module_id"]),
        course_id=None,
        language=language,
        level=1,
        country="BF",
        force=False,
        session_factory=lambda: None,
        units={u.module_unit_id: u for u in units},
        covering={u.module_unit_id: quiz_unit.module_unit_id for u in units if u.role == "lesson"},
        semaphore=asyncio.Semaphore(6),
        bible=bible(),
    )
    for unit in units:
        if unit.role == "lesson":
            run.lesson_rows[unit.module_unit_id] = SimpleNamespace(
                id=uuid.uuid5(unit.module_unit_id, "lesson"),
                content=lesson_content(unit.unit_number, language),
                content_revision=1,
                country_context="BF",
            )
    run.quiz_rows[quiz_unit.module_unit_id] = SimpleNamespace(
        id=uuid.UUID(int=15), content_revision=1, content={"questions": quiz_questions(language)}
    )
    ctx = module_ctx(language)
    run.request = service._plan_request(run, ctx, units, None)
    plan, gaps = normalise_plan(plan_answer(), run.request)
    assert gaps == [], gaps
    run.plan = EpisodePlan(
        plan=plan,
        inputs="inputs",
        digest=plan_digest(plan),
        global_digest=global_digest(plan),
        model="fake",
    )
    return service, run, ctx


async def tell(language: str) -> dict[str, Any]:
    """The whole episode in ``language``: plan, packs, chapters in order, rally, assembly."""
    service, run, ctx = make_run(language)
    units = story_units()
    lessons = [u for u in units if u.role == "lesson"]
    docs: dict[str, dict[str, Any] | None] = {}
    extras: dict[str, dict[str, Any]] = {}
    messages: dict[str, str] = {}
    pack_messages: dict[str, str] = {}
    contexts: dict[str, repair.LessonStoryContext] = {}
    for position, unit in enumerate(lessons):
        chapter = service._chapter_ctx(run, ctx, unit)
        the_pack = pack(unit.unit_number, language)
        assert pack_issues(chapter, the_pack) == [], unit.unit_number
        pack_messages[unit.unit_number] = build_pack_message(chapter)
        service._neighbours(chapter, run, lessons, position, docs, extras, {}, {})
        messages[unit.unit_number] = build_chapter_story_message(chapter, the_pack)
        model = FakeClaude(story_answer(unit.unit_number))
        generation = await StoryFromLessonService(model).generate_story(
            chapter, the_pack, system_prompt="system"
        )
        assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
        assert generation.report.warnings == [], [
            w.model_dump() for w in generation.report.warnings
        ]
        assert generation.model_calls == 1
        assert model.messages[0] == messages[unit.unit_number]
        docs[unit.unit_number] = generation.doc
        extras[unit.unit_number] = {
            "recap": generation.spine["recap"],
            "props_now": generation.spine["props_now"],
        }
        contexts[unit.unit_number] = chapter

    rally_unit = next(u for u in units if u.role == "quiz_checkpoint")
    rally_pack_ctx = service._rally_ctx(run, ctx, rally_unit, from_plan=True)
    rally_pack = pack("rally", language)
    assert pack_issues(rally_pack_ctx, rally_pack) == []
    pack_messages["rally"] = build_pack_message(rally_pack_ctx)
    rally_ctx = service._rally_ctx(run, ctx, rally_unit, from_plan=False, docs=docs)
    service._neighbours(rally_ctx, run, lessons, len(lessons), docs, extras, {}, {})
    rally_ctx.props_seen = _props_seen(docs)
    messages["rally"] = build_rally_story_message(rally_ctx, rally_pack)
    model = FakeClaude(story_answer("rally"))
    generation = await StoryFromLessonService(model).generate_story(
        rally_ctx, rally_pack, system_prompt="system", max_repair_calls=1
    )
    assert generation.report.ok, [e.model_dump() for e in generation.report.errors]
    assert generation.report.warnings == [], [w.model_dump() for w in generation.report.warnings]
    rally = generation.doc
    contexts["rally"] = rally_ctx

    sources = [ChapterSource(unit=u, doc=docs.get(u.unit_number)) for u in units]
    module = ModuleStoryContext(**{**ctx.__dict__, "episode_title": run.plan.plan["episode_title"]})
    doc = assemble_module_story(module, sources, rally)
    return {
        "doc": doc,
        "chapters": docs,
        "rally": rally,
        "messages": messages,
        "pack_messages": pack_messages,
        "contexts": contexts,
        "run": run,
        "plan_message": build_plan_user_message(run.request),
    }


@pytest.fixture(scope="module", params=LANGUAGES)
async def told(request) -> dict[str, Any]:
    return {"language": request.param, **(await tell(request.param))}


def chapter_steps(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for scene in chapter["scenes"] for step in scene["steps"]]


def is_line(step: dict[str, Any]) -> bool:
    return step["type"] in ("say", "narrate")


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_plan_answer_meets_every_plan_rule(language):
    _service, run, _ctx = make_run(language)
    assert validate_plan(plan_answer(), run.request) == []
    plan = run.plan.plan
    assert [c["unit"] for c in plan["chapters"]] == ["1.1", "1.2", "1.3"]
    assert [p["id"] for p in plan["props"]] == ["basket", "snail", "pebble", "nere_seed"]
    assert sum(bool(c["game"]) for c in plan["chapters"]) + bool(plan["rally"]["game"]) == 1


def test_the_plan_message_never_shows_a_wrong_option_or_a_misconception():
    _service, run, _ctx = make_run("fr")
    message = build_plan_user_message(run.request)
    assert SENTINEL not in message
    for q in data()["quiz"]:
        correct = q["options"]["fr"][q["correct_answer"]]
        assert correct in message
        for index, option in enumerate(q["options"]["fr"]):
            if index != q["correct_answer"]:
                assert f"«{option}»" not in message
    # The lesson's own example people and towns are named only as forbidden.
    assert "Never use these names" in message
    assert "Aminata" in run.request.blocklist and "Bouaké" in run.request.blocklist
    assert "Kaboré" not in run.request.blocklist and "Mariam" not in run.request.blocklist
    assert "INTRODUCTION:" not in message and "FIELD EXAMPLE" not in message


def test_the_bible_answer_is_normalised_to_the_contract():
    content = bible().content
    cast = {member["id"]: member for member in content["cast"]}
    assert list(cast) == ["hero", "friend", "mentor", "family", "margo"]
    assert cast["hero"]["name"] == "{child}" and cast["friend"]["name"] == "{friend}"
    assert cast["mentor"]["name"] == "Kaboré"
    assert [p["id"] for p in content["places"]][:3] == [
        "rood_woko_market",
        "courtyard",
        "classroom",
    ]


# --------------------------------------------------------------------------
# The module story
# --------------------------------------------------------------------------


async def test_the_module_story_validates_with_zero_errors_and_zero_warnings(told):
    doc = told["doc"]
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    assert report.warnings == [], [w.model_dump() for w in report.warnings]
    direct = validate_story_course(
        StoryCourse.model_validate(json.loads(json.dumps(doc))), generated=True
    )
    assert direct.ok and direct.warnings == []


async def test_one_chapter_per_lesson_then_the_rally_with_story_titles(told):
    doc = told["doc"]
    language = told["language"]
    chapters = doc["chapters"]
    covers = [c["covers"] for c in chapters]
    assert [c["unit_number"] for c in covers] == ["1.1", "1.2", "1.3", "1.5"]
    for cover in covers[:3]:
        assert cover["status"] == "ready" and cover["completes_unit"] is True
    assert covers[3]["rally"] is True and covers[3]["completes_unit"] is False
    plan = plan_answer()
    assert [c["title"] for c in chapters[:3]] == [c["title"] for c in plan["chapters"]]
    assert chapters[3]["title"] == plan["rally"]["title"]
    assert all("·" not in c["title"][language] for c in chapters)
    assert doc["title"] == plan["episode_title"]
    assert doc["unit"].startswith("Module 1 · ")


async def test_the_cast_places_and_props_are_the_storys(told):
    doc = told["doc"]
    assert doc["cast"] == doc_cast(bible().content)
    assert doc["places"] == doc_places(bible().content)
    place_ids = {p["id"] for p in doc["places"]}
    prop_ids = {p["id"] for p in doc["props"]}
    assert {"basket", "snail", "pebble", "nere_seed", "mimosa", "microscope"} <= prop_ids
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            assert scene["place"] in place_ids
            assert 2 <= len(scene["cast"]) <= 3
            assert set(scene.get("props") or []) <= prop_ids
            for step in scene["steps"]:
                if step["type"] == "say":
                    assert step["who"] in scene["cast"] and step["mood"] in MOODS
                assert set(step.get("props") or []) <= set(scene.get("props") or [])


async def test_every_line_is_dialogue_or_narration_within_its_limits(told):
    names = re.compile(
        r"^(?:mr|m\.|mme)?\s*(kaboré|mariam|margo|\{friend\}|\{child\})\s*(:|says|dit)", re.I
    )
    for chapter in told["doc"]["chapters"]:
        for step in chapter_steps(chapter):
            if not is_line(step):
                continue
            assert len(step["en"]) <= 100 and len(step["fr"]) <= 118, step
            if step["type"] == "say":
                assert not names.match(step["en"]) and not names.match(step["fr"]), step


async def test_no_line_is_told_twice_but_the_refrain(told):
    seen: dict[tuple[str, str], str] = {}
    refrains = 0
    for chapter in told["doc"]["chapters"]:
        for step in chapter_steps(chapter):
            if not is_line(step):
                continue
            assert not step.get("retold"), step
            if step.get("refrain"):
                refrains += 1
                assert step["en"] == "Detectives, to work!"
                continue
            for lang in ("en", "fr"):
                key = (lang, line_key(step[lang]))
                assert seen.setdefault(key, chapter["id"]) == chapter["id"], step
    assert refrains == 3


async def test_every_lesson_concept_is_taught(told):
    for chapter in told["doc"]["chapters"][:3]:
        taught = sorted(
            n for s in chapter_steps(chapter) for n in repair.taught(s) if s["type"] == "concept"
        )
        assert taught == [1, 2, 3], chapter["id"]
        assert len(chapter["scenes"]) == 3


async def test_each_question_follows_its_idea_with_lead_in_and_reaction(told):
    for chapter in told["doc"]["chapters"]:
        steps = chapter_steps(chapter)
        for index, step in enumerate(steps):
            if step["type"] != "ask":
                continue
            before = index - 1
            while steps[before]["type"] in ("ask",) or "situation-" in str(steps[before].get("id")):
                before -= 1
            assert steps[before]["type"] == "say", (chapter["id"], step["ref"])
            after = index + 1
            while steps[after]["type"] == "ask":
                after += 1
            assert is_line(steps[after]), (chapter["id"], step["ref"])
    # The plan put each question in the beat of the idea it tests: after its card.
    for unit in ("1.1", "1.2", "1.3"):
        doc = told["chapters"][unit]
        steps = chapter_steps(doc["chapters"][0])
        ideas = dict(data()["packs"][unit]["derived_ideas"])
        for question in data()["packs"][unit]["questions"]:
            ideas[question["id"]] = question["idea"]
        for index, step in enumerate(steps):
            if step["type"] == "ask":
                cards = [s for s in steps[:index] if s["type"] == "concept"]
                assert ideas[step["ref"]] in repair.taught(cards[-1]), (unit, step["ref"])


async def test_story_lines_dominate(told):
    for key in ("1.1", "1.2", "1.3", "rally"):
        doc = told["rally"] if key == "rally" else told["chapters"][key]
        quality = doc["checks"]["story_quality"]
        assert quality["ratio"] >= 0.6, (key, quality)
        assert quality["min_gap"] is None or quality["min_gap"] >= 3, (key, quality)
        assert quality["lead_ins_missing"] == 0 and quality["reactions_missing"] == 0
        assert quality["names_leaked"] == 0 and quality["lecture_lines"] == 0
        assert quality["fallback_cards"] == 0 and quality["card_echoes"] == 0


async def test_chapters_end_on_story_line(told):
    for chapter in told["doc"]["chapters"]:
        steps = chapter_steps(chapter)
        assert is_line(steps[-1]), chapter["id"]
        assert all(s["type"] not in ("game", "photo") for s in steps[-3:]), chapter["id"]


async def test_rally_ends_on_payoff_not_task(told):
    rally = told["doc"]["chapters"][-1]
    steps = chapter_steps(rally)
    assert steps[-1]["type"] == "narrate"
    assert steps[-1]["en"].startswith("{friend} ties a tiny ribbon on the pebble")
    assert "pebble" in steps[-1]["props"]
    assert [s["type"] for s in steps].count("concept") <= 1


async def test_every_prop_a_line_names_is_on_stage_and_shown_close_up(told):
    doc = told["doc"]
    checks = validate_module_story(doc).checks.props
    assert checks["declared"] == len(doc["props"]) and checks["scenes_without_visual"] == 0
    educational = {p["id"] for p in doc["props"] if p["educational"]}
    shown = {
        s["params"]["prop"]
        for c in doc["chapters"]
        for s in chapter_steps(c)
        if s["type"] == "show" and s.get("visual") == "prop"
    }
    assert educational <= shown
    snail = next(p for p in doc["props"] if p["id"] == "snail")
    assert snail["kind"] == "real" and snail["educational"] and snail["query"] == "garden snail"
    fan = next(p for p in doc["props"] if p["id"] == "fan")
    assert fan["kind"] == "sticker" and fan["at"] == "held" and fan["holder"] == "hero"


async def test_the_quiz_is_verbatim_and_its_misconceptions_never_reach_the_story(told):
    language = told["language"]
    doc = told["doc"]
    text = json.dumps(doc, ensure_ascii=False)
    assert SENTINEL not in text and "option_misconceptions" not in text
    for key, message in told["messages"].items():
        assert SENTINEL not in message, key
    assert SENTINEL not in told["plan_message"]
    assert all(SENTINEL in told["pack_messages"][k] for k in ("1.1", "1.2", "1.3", "rally"))
    stored = {q["id"]: q for q in quiz_questions(language)}
    derived = [q for q in doc["questions"] if q.get("derived_from")]
    assert len(derived) == 12
    for question in derived:
        source = stored[question["derived_from"]["question_id"]]
        assert [c[language] for c in question["choices"]] == source["options"]
        assert question["answer"] == "abcd"[source["correct_answer"]]
        assert question.get("stem", question["prompt"])[language] == source["question"]


async def test_messages_carry_no_lecture_template(told):
    forbidden = (
        "STRICT CONSTRAINT",
        "one episode",
        "INTRODUCTION:",
        "FIELD EXAMPLE:",
        "SYNTHESIS:",
        "SOURCES:",
        "Essaie toi-même",
        "Bloom",
        "hundred_square",
        "Bouaké, Aminata",
    )
    for key, message in {**told["messages"], **told["pack_messages"]}.items():
        for text in forbidden:
            assert text not in message, (key, text)
    assert "This is the first chapter: the story starts here." in told["messages"]["1.1"]
    assert "=== WHERE THE LAST CHAPTER STOPPED" not in told["messages"]["1.1"]
    assert "=== WHERE THE LAST CHAPTER STOPPED" in told["messages"]["1.2"]
    assert "► 2." in told["messages"]["1.2"]
    assert "PROPS NOW:" in told["messages"]["1.2"]


async def test_each_chapter_is_told_after_the_one_before_it(told):
    """Story k's message carries chapter k-1's real last scene and recap (#2680)."""
    language = told["language"]
    for previous, current in (("1.1", "1.2"), ("1.2", "1.3"), ("1.3", "rally")):
        message = told["messages"][current]
        before = told["chapters"][previous]["chapters"][0]["scenes"][-1]["steps"]
        last_line = next(s for s in reversed(before) if is_line(s))
        assert last_line[language] in message, (current, last_line[language])
        recap = data()["stories"][previous]["recap"]
        assert recap in message
    rally = told["messages"]["rally"]
    for key in ("1.1", "1.2", "1.3"):
        for step in chapter_steps(told["chapters"][key]["chapters"][0]):
            if step["type"] == "concept":
                assert step["title"][language] in rally


async def test_fixture_continuity_is_reachable(told):
    """Whatever a chapter shares with another is in that chapter's BUILT message.

    A prop id, a weekday or a name a chapter's answer uses and another
    chapter's uses too must reach it through its message (the plan, the
    story so far, the previous chapter's last scene): a hand-written
    continuity the pipeline could not carry fails here.
    """
    language = told["language"]
    tokens: dict[str, set[str]] = {}
    for key in ("1.1", "1.2", "1.3", "rally"):
        tokens[key] = _continuity_tokens(data()["stories"][key], language)
    for key, mine in tokens.items():
        message = told["messages"][key].casefold()
        for token in mine:
            shared = any(
                token in theirs for other_key, theirs in tokens.items() if other_key != key
            )
            if not shared:
                continue
            forms = {token, WEEKDAYS.get(token, token)} | {
                en for en, fr in WEEKDAYS.items() if fr == token
            }
            assert any(form.casefold() in message for form in forms), (key, token)


def _continuity_tokens(answer: dict[str, Any], language: str) -> set[str]:
    out: set[str] = set()
    for scene in answer["scenes"]:
        out.update(scene.get("props") or [])
        for step in scene["steps"]:
            out.update(step.get("props") or [])
            if step.get("prop"):
                out.add(step["prop"])
            text = step.get(language)
            texts = text if isinstance(text, list) else [text] if isinstance(text, str) else []
            for value in texts:
                folded = value.casefold()
                out.update(day for day, fr in WEEKDAYS.items() if day in folded or fr in folded)
                for match in re.finditer(r"(?<=[^.!?…:«\s]\s)([A-ZÉ][\wé]{2,})", value):
                    word = match.group(1)
                    if not word.isupper():
                        out.add(word.casefold())
    return out


async def test_the_chapter_markers_name_what_it_was_told_with(told):
    run = told["run"]
    for unit in ("1.1", "1.2", "1.3"):
        marker = told["chapters"][unit]["sira_chapter"]
        assert marker["kind"] == "lesson" and marker["bible"] == bible().digest
        assert marker["plan"] == run.plan.global_digest
        assert marker["beat"] == run.plan.beat_digest(unit, run.request)
        assert marker["fact_sheet"] == fact_sheet_digest(lesson_content(unit, told["language"]))
        assert told["chapters"][unit]["sira_builder"] == repair.CHAPTER_BUILDER_VERSION == 4
    assert told["rally"]["sira_chapter"]["kind"] == "rally"
