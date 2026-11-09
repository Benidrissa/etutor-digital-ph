"""The module story assembler (contract C-2), on real chapter documents.

The fixture ``fixtures/module_story_chapters.json`` holds the screenplay
module of ``story_screenplay_module.json`` — lessons 1.1, 1.2 and 1.3, the
case study 1.4 and the quiz unit 1.5 — as the real pipeline makes it
(:func:`tests.test_story_screenplay_module.tell`, a fake model returning the
fixture's answers): the course bible, the three lessons' chapter documents
and the rally's, with French and with English as the language of
instruction. The quiz's ``option_misconceptions`` are sentinel strings, so a
test can prove they never reach a story. ``test_the_fixture_is_what_the_pipeline_makes``
rebuilds it and fails when the generator changes; regenerate with::

    STORY_FIXTURE_REGEN=1 uv run pytest tests/test_story_module_assembly.py \
        -k the_fixture_is_what_the_pipeline_makes

The assembler adds no line of its own (#2674): one chapter per lesson, the
rally last, nothing for quiz or case-study units, the bible's cast and places.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import random
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.api.v1.schemas.story_course import StoryCourse
from app.domain.services import story_module_assembly as assembly
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import StoryBible, doc_cast, doc_facts, doc_places
from app.domain.services.story_course_validator import validate_story_course
from app.domain.services.story_module_assembly import (
    ChapterSource,
    ModuleStoryContext,
    StoryUnit,
    assemble_module_story,
    module_story_slug,
    unit_role,
    validate_module_story,
)
from tests import test_story_screenplay_module as screenplay

FIXTURES = Path(__file__).parent / "fixtures"
MODULE_FIXTURE = FIXTURES / "module_story_chapters.json"

SENTINEL = screenplay.SENTINEL
LANGUAGES = ("fr", "en")
LESSONS = ("1.1", "1.2", "1.3")
REF_TYPES = ("ask", "game", "photo", "video")


def _undated(doc: dict[str, Any]) -> dict[str, Any]:
    doc = copy.deepcopy(doc)
    doc.get("checks", {}).pop("date", None)
    return doc


@pytest.fixture(scope="module")
def fixture() -> dict[str, Any]:
    return json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))


async def test_the_fixture_is_what_the_pipeline_makes():
    told = {language: await screenplay.tell(language) for language in LANGUAGES}
    data = screenplay.data()
    if os.environ.get("STORY_FIXTURE_REGEN") == "1":
        regenerated = {
            "_comment": (
                "Module story fixture: the screenplay module of story_screenplay_module.json"
                " as the pipeline makes it — its bible, lesson chapters and rally."
                " Regenerate with STORY_FIXTURE_REGEN=1 (see test_story_module_assembly.py)."
            ),
            "module": data["module"],
            "units": data["units"],
            "bible": screenplay.bible().content,
            "quiz": {language: screenplay.quiz_questions(language) for language in LANGUAGES},
            "chapters": {language: told[language]["chapters"] for language in LANGUAGES},
            "rally": {language: told[language]["rally"] for language in LANGUAGES},
        }
        MODULE_FIXTURE.write_text(
            json.dumps(regenerated, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    stored = json.loads(MODULE_FIXTURE.read_text(encoding="utf-8"))
    assert stored["units"] == data["units"] and stored["module"] == data["module"]
    assert stored["bible"] == screenplay.bible().content
    for language in LANGUAGES:
        assert stored["quiz"][language] == screenplay.quiz_questions(language)
        assert sorted(stored["chapters"][language]) == list(LESSONS)
        for number, doc in told[language]["chapters"].items():
            assert _undated(stored["chapters"][language][number]) == _undated(doc), number
        assert _undated(stored["rally"][language]) == _undated(told[language]["rally"])


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
        "bible": StoryBible.of(fixture["bible"]),
    }
    values.update(overrides)
    return ModuleStoryContext(**values)


def chapter_sources(fixture: dict[str, Any], language: str) -> list[ChapterSource]:
    docs = fixture["chapters"][language]
    return [
        ChapterSource(unit=unit, doc=copy.deepcopy(docs.get(unit.unit_number)))
        for unit in story_units(fixture)
    ]


def rally(fixture: dict[str, Any], language: str) -> dict[str, Any]:
    return copy.deepcopy(fixture["rally"][language])


def assemble(fixture: dict[str, Any], language: str, **overrides: Any) -> dict[str, Any]:
    return assemble_module_story(
        module_ctx(fixture, language, **overrides),
        chapter_sources(fixture, language),
        rally(fixture, language),
    )


def chapter_steps(chapter: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for scene in chapter["scenes"] for step in scene["steps"]]


def all_steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for chapter in doc["chapters"] for step in chapter_steps(chapter)]


def expected_prefixes(units: list[StoryUnit]) -> list[str]:
    """C-2's ``u{key}-`` per told chapter, a repeated key made unique with ``_2``, ``_3``…"""
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


def owned(items: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [item for item in items if item["id"].startswith(prefix)]


def source_step(step: dict[str, Any], prefix: str) -> dict[str, Any]:
    step = copy.deepcopy(step)
    if step.get("id"):
        step["id"] = strip(step["id"], prefix)
    if step["type"] in REF_TYPES and step.get("ref"):
        step["ref"] = strip(step["ref"], prefix)
    return step


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
    places = {p["id"] for p in doc["places"]}
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
        for trap in question.get("traps", []):
            assert trap["misconception"] in misconceptions
    for game in doc["minigames"]:
        for round_data in game["rounds"]:
            for item in round_data.get("items", []):
                assert item.get("trap") is None or item["trap"] in misconceptions
    for chapter in doc["chapters"]:
        for scene in chapter["scenes"]:
            assert scene["place"] in places
            assert set(scene.get("cast") or []) <= cast
            assert scene.get("objective") is None or scene["objective"] in objectives
            for step in scene["steps"]:
                if step["type"] in targets:
                    assert step["ref"] in targets[step["type"]], step
                if step["type"] == "say":
                    assert step["who"] in cast
    assert set(doc["tutor"]["scope"]["this_week"]) == objectives
    assert doc["tutor"]["persona"] in cast
    asked = [s["ref"] for s in all_steps(doc) if s["type"] == "ask"]
    assert sorted(asked) == sorted(q["id"] for q in doc["questions"])


def check_no_text_changed(
    doc: dict[str, Any], sources: list[ChapterSource], rally_source: ChapterSource | None = None
) -> None:
    """Every step of a ready chapter is the chapter's own, ids aside, in order.

    Apart from the steps of questions dropped as duplicates and lines already
    told by an earlier chapter. ``sources`` are the module's units in order;
    ``rally_source`` is the rally, told last.
    """
    told = [s for s in sources if s.unit.role == "lesson"]
    if rally_source is not None:
        told.append(rally_source)
    prefixes = expected_prefixes([s.unit for s in told])
    for index, (source, chapter) in enumerate(zip(told, doc["chapters"], strict=True)):
        if chapter["covers"]["status"] == "unavailable" or source.doc is None:
            continue
        prefix = prefixes[index]
        kept = {strip(q["id"], prefix) for q in owned(doc["questions"], prefix)}
        module_questions = {
            strip(q["id"], prefix): source_question(q, prefix)
            for q in owned(doc["questions"], prefix)
        }
        for question in source.doc["questions"]:
            if question["id"] in kept:
                expected = {k: v for k, v in question.items() if k != "option_misconceptions"}
                assert module_questions[question["id"]] == expected
        dropped = {q["id"] for q in source.doc["questions"]} - kept
        situations = {repair.situation_step_id(qid) for qid in dropped}
        expected_steps = [
            step
            for c in source.doc["chapters"]
            for sc in c["scenes"]
            for step in sc["steps"]
            if not (step["type"] == "ask" and step["ref"] in dropped)
            and not (step["type"] == "concept" and step["id"] in situations)
        ]
        module_steps = [source_step(s, prefix) for s in chapter_steps(chapter)]
        remaining = iter(expected_steps)
        for step in module_steps:
            # In order: a step skipped in between is a line told earlier.
            assert any(step == candidate for candidate in remaining), step


def revision_of(doc: dict[str, Any], told: list[tuple[ChapterSource, str]], bible: str) -> str:
    """C-2's revision, computed independently of the assembler."""

    def canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    rows: list[list[Any]] = [
        [
            str(s.unit.module_unit_id),
            kind,
            hashlib.sha256(canonical(s.doc).encode()).hexdigest() if s.doc is not None else None,
        ]
        for s, kind in told
    ]
    rows.append(["bible", bible, repair.CHAPTER_BUILDER_VERSION])
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
    direct = validate_story_course(StoryCourse.model_validate(json.loads(json.dumps(doc))))
    assert direct.ok and direct.warnings == []
    # 3 + 3 + 3 course questions and 2 of the packs' own, then the rally's 3.
    assert report.checks.questions == len(doc["questions"]) == 9 + 2 + 3


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
    assert doc["week"] == 1 and doc["title"] == title  # no episode title given
    assert doc["languages"] == {"target": language, "home": "fr" if language == "en" else "en"}
    assert doc["learner"] == {"first_name": "{child}"}
    assert doc["cast"] == doc_cast(fixture["bible"])
    assert doc["places"] == doc_places(fixture["bible"])
    assert set(doc["checks"]) == {"predicted_typical"}
    assert doc["module_story"] == {
        "module_id": str(module_id),
        "module_number": 1,
        "assembler": assembly.MODULE_ASSEMBLER_VERSION,
        "generator": repair.CHAPTER_BUILDER_VERSION,
        "bible": StoryBible.of(fixture["bible"]).digest,
        "revision": doc["module_story"]["revision"],
    }
    assert assembly.MODULE_ASSEMBLER_VERSION == 3
    episode = {"en": "The basket of mysteries", "fr": "Le panier des mystères"}
    assert assemble(fixture, language, episode_title=episode)["title"] == episode
    assert "sira_builder" not in doc


@pytest.mark.parametrize("language", LANGUAGES)
def test_one_chapter_per_lesson_then_the_rally_with_its_covers(fixture, language):
    doc = assemble(fixture, language)
    units = {u["unit_number"]: u for u in fixture["units"]}
    assert [c["id"] for c in doc["chapters"]] == ["ch1", "ch2", "ch3", "ch4"]
    for chapter, number in zip(doc["chapters"][:3], LESSONS, strict=True):
        covers = chapter["covers"]
        assert covers == {
            "module_unit_id": units[number]["module_unit_id"],
            "unit_number": number,
            "unit_type": "lesson",
            "role": "lesson",
            "status": "ready",
            "completes_unit": True,
            "max_points": covers["max_points"],
        }
        # #2680: the plan's story title, no "1.2 · " prefix (the chapter list
        # shows "Leçon 1.2" from covers.unit_number).
        assert chapter["title"] == fixture["chapters"][language][number]["chapters"][0]["title"]
        assert "·" not in chapter["title"]["en"]
    rally_chapter = doc["chapters"][3]
    assert rally_chapter["covers"] == {
        "module_unit_id": units["1.5"]["module_unit_id"],
        "unit_number": "1.5",
        "unit_type": "quiz",
        "role": "quiz_checkpoint",
        "status": "checkpoint",
        "completes_unit": False,
        "max_points": rally_chapter["covers"]["max_points"],
        "rally": True,
    }
    assert rally_chapter["title"] == fixture["rally"][language]["chapters"][0]["title"]
    assert "1.4" not in {c["covers"]["unit_number"] for c in doc["chapters"]}


@pytest.mark.parametrize("language", LANGUAGES)
def test_max_points_per_chapter_add_up_to_the_module(fixture, language):
    doc = assemble(fixture, language)
    points = {c["covers"]["unit_number"]: c["covers"]["max_points"] for c in doc["chapters"]}
    for number in LESSONS:
        assert points[number] == fixture["chapters"][language][number]["checks"]["max_points"] > 0
    assert points["1.5"] == fixture["rally"][language]["checks"]["max_points"] > 0
    assert sum(points.values()) == validate_module_story(doc).checks.max_points
    typical = doc["checks"]["predicted_typical"]
    assert 0 < typical["points"] <= sum(points.values())
    assert typical["plan"].startswith("Lesson 1.1:") and "Rally:" in typical["plan"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_ids_are_unique_and_every_reference_resolves(fixture, language):
    doc = assemble(fixture, language)
    check_ids_unique(doc)
    check_references_resolve(doc)
    ids = {q["id"] for q in doc["questions"]}
    assert {"u1_1-q1", "u1_2-q4", "u1_1-x1", "u1_5-q10"} <= ids


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_learner_facing_text_changes(fixture, language):
    doc = assemble(fixture, language)
    the_rally = ChapterSource(story_units(fixture)[4], rally(fixture, language))
    check_no_text_changed(doc, chapter_sources(fixture, language), the_rally)
    assert all("frame" not in step for step in all_steps(doc))


@pytest.mark.parametrize("language", LANGUAGES)
def test_quiz_mcqs_stay_verbatim(fixture, language):
    doc = assemble(fixture, language)
    quiz = {q["id"]: q for q in fixture["quiz"][language]}
    derived = [q for q in doc["questions"] if "derived_from" in q]
    assert len(derived) == 12
    for question in derived:
        assert question["derived_from"]["quiz_unit"] == "1.5"
        mcq = quiz[question["derived_from"]["question_id"]]
        assert [c[language] for c in question["choices"]] == mcq["options"]
        assert question["answer"] == "abcdef"[mcq["correct_answer"]]
        assert question.get("stem", question["prompt"])[language] == mcq["question"]
        assert question["explanation"][language] == mcq["explanation"]


def _with_a_copy(fixture: dict[str, Any], language: str, into: str, *, extras: bool = True):
    """Lesson ``into``'s chapter also asks 1.1's first quiz question, after its last card."""
    sources = chapter_sources(fixture, language)
    first = next(s.doc for s in sources if s.unit.unit_number == "1.1")
    target = next(s.doc for s in sources if s.unit.unit_number == into)
    copied = copy.deepcopy(next(q for q in first["questions"] if q["id"] == "q2"))
    copied["id"] = "q99"
    target["questions"].append(copied)
    target["misconceptions"] += [
        m
        for m in first["misconceptions"]
        if m["id"] in {c.get("misconception") for c in copied["choices"]}
        and m["id"] not in {x["id"] for x in target["misconceptions"]}
    ]
    target["chapters"][0]["scenes"][0]["steps"].append({"type": "ask", "ref": "q99"})
    target["checks"]["max_points"] += 2  # the generator counts it
    if not extras:
        keep = {"q99", next(q["id"] for q in target["questions"] if q["id"] != "q99")}
        dropped = {q["id"] for q in target["questions"]} - keep
        target["checks"]["max_points"] -= 2 * len(dropped)
        target["questions"] = [q for q in target["questions"] if q["id"] in keep]
        for scene in target["chapters"][0]["scenes"]:
            scene["steps"] = [s for s in scene["steps"] if s.get("ref") not in dropped]
    return sources


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_later_copy_is_dropped_unless_its_chapter_would_fall_below_the_floor(fixture, language):
    sources = _with_a_copy(fixture, language, "1.2")
    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))
    assert "u1_2-q99" not in {q["id"] for q in doc["questions"]}
    assert not [s for s in all_steps(doc) if s.get("ref") == "u1_2-q99"]
    assert validate_module_story(doc).ok
    points = {c["covers"]["unit_number"]: c["covers"]["max_points"] for c in doc["chapters"]}
    assert points["1.2"] == fixture["chapters"][language]["1.2"]["checks"]["max_points"]

    # Kept when dropping it would leave the chapter one question.
    thin = _with_a_copy(fixture, language, "1.3", extras=False)
    doc = assemble_module_story(module_ctx(fixture, language), thin, rally(fixture, language))
    assert "u1_3-q99" in {q["id"] for q in doc["questions"]}


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_rally_keeps_a_review_question(fixture, language):
    """A question the rally asks again on purpose is never de-duplicated."""
    rally_doc = rally(fixture, language)
    first = chapter_sources(fixture, language)[0].doc
    review = copy.deepcopy(next(q for q in first["questions"] if q["id"] == "q1"))
    review["id"] = "q13"
    rally_doc["questions"].append(review)
    rally_doc["misconceptions"] += [
        m
        for m in first["misconceptions"]
        if m["id"] not in {x["id"] for x in rally_doc["misconceptions"]}
    ]
    steps = rally_doc["chapters"][0]["scenes"][0]["steps"]
    ask = next(i for i, s in enumerate(steps) if s.get("type") == "ask")
    steps.insert(ask + 2, {"type": "ask", "ref": "q13"})
    steps.insert(ask + 3, {"type": "say", "who": "hero", "en": "Again!", "fr": "Encore !"})
    doc = assemble_module_story(
        module_ctx(fixture, language), chapter_sources(fixture, language), rally_doc
    )
    q1 = [q["id"] for q in doc["questions"] if q.get("derived_from", {}).get("question_id") == "q1"]
    assert sorted(q1) == ["u1_1-q1", "u1_5-q13"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_line_told_in_an_earlier_chapter_is_kept_and_marked_retold(fixture, language):
    """#2680: deleting it left gaps in the dialogue; it is kept, marked ``retold``."""
    sources = chapter_sources(fixture, language)
    first = next(s.doc for s in sources if s.unit.unit_number == "1.1")
    second = next(s.doc for s in sources if s.unit.unit_number == "1.2")
    told = copy.deepcopy(first["chapters"][0]["scenes"][0]["steps"][1])
    second["chapters"][0]["scenes"][0]["steps"].insert(1, told)
    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))
    lines = [s for s in chapter_steps(doc["chapters"][1]) if s["type"] in ("say", "narrate")]
    kept = next(s for s in lines if s["en"] == told["en"])
    assert kept["retold"] is True
    report = validate_module_story(doc)
    assert report.ok and "repeated_line" not in {w.code for w in report.warnings}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_refrain_is_never_marked_retold(fixture, language):
    doc = assemble(fixture, language)
    refrains = [s for s in all_steps(doc) if s.get("refrain")]
    assert len(refrains) == 3 and not any(s.get("retold") for s in refrains)
    assert validate_module_story(doc).ok


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
    assert assemble(fixture, language)["tutor"]["scope"]["earlier_weeks"] is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_sources_and_facts_are_merged_without_duplicates(fixture, language):
    doc = assemble(fixture, language)
    keys = [(s["kind"], s["ref"]) for s in doc["sources"]]
    assert len(keys) == len(set(keys))
    assert keys.count(("test", "Unit 1.5 quiz")) == 1
    for number in LESSONS:
        assert any(kind == "lesson" and ref.startswith(f"Lesson {number} ") for kind, ref in keys)
    facts = [(f["en"], f["fr"]) for f in doc["facts"]]
    assert len(facts) == len(set(facts))
    assert doc["facts"][: len(fixture["bible"]["facts"])] == doc_facts(fixture["bible"])


def test_a_kids_module_uses_the_kids_rewards(fixture):
    assert assemble(fixture, "fr")["rewards"]["unit"] == {"en": "mangoes", "fr": "mangues"}
    assert assemble(fixture, "fr", is_kids=False)["rewards"]["unit"] == {
        "en": "points",
        "fr": "points",
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_runs_of_questions_never_carry_across_a_chapter_end(fixture, language):
    """Three asks closing a chapter and three opening the next: each chapter is fine."""
    sources = chapter_sources(fixture, language)
    first = next(s.doc for s in sources if s.unit.unit_number == "1.1")
    second = next(s.doc for s in sources if s.unit.unit_number == "1.2")
    last_scene = first["chapters"][0]["scenes"][-1]["steps"]
    last_scene += [{"type": "narrate", "en": "Ready?", "fr": "Prêts ?"}]
    second["chapters"][0]["scenes"][0]["steps"].insert(0, {"type": "ask", "ref": "q4"})
    second["chapters"][0]["scenes"][0]["steps"] = [
        s
        for i, s in enumerate(second["chapters"][0]["scenes"][0]["steps"])
        if not (s.get("ref") == "q4" and i > 0)
    ]
    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))
    assert validate_module_story(doc).ok


# --------------------------------------------------------------------------
# Revision, determinism, purity, sentinels
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_revision_is_the_documented_digest(fixture, language):
    sources = chapter_sources(fixture, language)
    the_rally = rally(fixture, language)
    doc = assemble_module_story(module_ctx(fixture, language), sources, the_rally)
    units = story_units(fixture)
    told = [(s, "lesson") for s in sources if s.unit.role == "lesson"]
    told.append((ChapterSource(units[4], the_rally), "rally"))
    bible = StoryBible.of(fixture["bible"]).digest
    assert doc["module_story"]["revision"] == revision_of(doc, told, bible)


def test_the_revision_changes_with_a_chapter_the_rally_or_the_bible(fixture):
    base = assemble(fixture, "en")["module_story"]["revision"]
    # Another context (not kids, a previous module) is not a chapter change.
    assert assemble(fixture, "en", is_kids=False)["module_story"]["revision"] == base

    sources = chapter_sources(fixture, "en")
    sources[1].doc["questions"][0]["explanation"]["fr"] += " Voilà."
    edited = assemble_module_story(module_ctx(fixture, "en"), sources, rally(fixture, "en"))
    assert edited["module_story"]["revision"] != base

    no_rally = assemble_module_story(module_ctx(fixture, "en"), chapter_sources(fixture, "en"))
    assert no_rally["module_story"]["revision"] not in (base, edited["module_story"]["revision"])

    other_bible = copy.deepcopy(fixture["bible"])
    other_bible["places"][0]["look"] += " at dusk"
    rebibled = assemble(fixture, "en", bible=StoryBible.of(other_bible))
    assert rebibled["module_story"]["revision"] != base
    assert rebibled["places"][0]["look"].endswith("at dusk")


@pytest.mark.parametrize("language", LANGUAGES)
def test_assembly_is_deterministic_and_never_mutates_its_inputs(fixture, language):
    sources = chapter_sources(fixture, language)
    the_rally = rally(fixture, language)
    before = copy.deepcopy([s.doc for s in sources] + [the_rally])
    first = assemble_module_story(module_ctx(fixture, language), sources, the_rally)
    second = assemble_module_story(module_ctx(fixture, language), sources, the_rally)
    assert json.dumps(first, ensure_ascii=False) == json.dumps(second, ensure_ascii=False)
    assert [s.doc for s in sources] + [the_rally] == before
    first["questions"][0]["prompt"]["en"] = "changed"
    first["chapters"][1]["scenes"][0]["steps"][0]["en"] = "changed"
    first["cast"][0]["look"] = "changed"
    assert [s.doc for s in sources] + [the_rally] == before
    assert fixture["bible"]["cast"][0]["look"] != "changed"


def test_option_misconceptions_never_reach_a_story(fixture):
    assert all(
        any(isinstance(m, str) and m.startswith(SENTINEL) for m in q["option_misconceptions"])
        for language in LANGUAGES
        for q in fixture["quiz"][language]
    )
    for language in LANGUAGES:
        assert SENTINEL not in json.dumps(fixture["chapters"][language], ensure_ascii=False)
        assert SENTINEL not in json.dumps(fixture["rally"][language], ensure_ascii=False)
        assert SENTINEL not in json.dumps(assemble(fixture, language), ensure_ascii=False)


def test_a_stray_option_misconceptions_key_is_never_copied(fixture):
    sources = chapter_sources(fixture, "en")
    planted = sources[0].doc["questions"][0]
    planted["option_misconceptions"] = [None, f"{SENTINEL}-planted", None, None]
    planted["choices"][1]["option_misconceptions"] = f"{SENTINEL}-nested"
    the_rally = rally(fixture, "en")
    the_rally["questions"][0]["option_misconceptions"] = [f"{SENTINEL}-rally"]
    before = copy.deepcopy(sources[0].doc)

    doc = assemble_module_story(module_ctx(fixture, "en"), sources, the_rally)

    text = json.dumps(doc, ensure_ascii=False)
    assert SENTINEL not in text and "option_misconceptions" not in text
    assert sources[0].doc == before
    assert validate_module_story(doc).ok


# --------------------------------------------------------------------------
# Unusable chapter documents become placeholders; an unusable rally is left out
# --------------------------------------------------------------------------


def _old_builder(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc.pop("sira_builder")
    return doc


def _builder_two(doc: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    doc["sira_builder"] = 2
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


SPOILERS = [_old_builder, _builder_two, _other_language, _other_unit, _malformed, _no_chapters]


@pytest.mark.parametrize(
    "spoil", [*SPOILERS, None], ids=lambda f: f.__name__.strip("_") if f else "none"
)
def test_an_unusable_chapter_becomes_a_placeholder(fixture, spoil):
    sources = chapter_sources(fixture, "en")
    doc = copy.deepcopy(sources[1].doc)
    sources[1] = ChapterSource(sources[1].unit, spoil(doc, fixture) if spoil else None)

    module = assemble_module_story(module_ctx(fixture, "en"), sources, rally(fixture, "en"))

    covers = module["chapters"][1]["covers"]
    assert (covers["status"], covers["completes_unit"], covers["max_points"]) == (
        "unavailable",
        False,
        0,
    )
    steps = chapter_steps(module["chapters"][1])
    # #2680: one line in the story's voice; the player adds its open-the-lesson button.
    assert [(s["type"], s["frame"]) for s in steps] == [("narrate", "unavailable")]
    assert steps[0]["en"] == assembly.STILL_BEING_WRITTEN["en"]
    assert steps[0]["fr"] == "Cette partie de l'aventure est encore en cours d'écriture."
    assert not [q for q in module["questions"] if q["id"].startswith("u1_2-")]
    report = validate_module_story(module)
    assert report.ok, [e.model_dump() for e in report.errors]
    # Chapter 1.2 holds the episode's one game: until it is ready, a warning.
    assert {w.code for w in report.warnings} <= {"missing_minigame"}


@pytest.mark.parametrize("spoil", SPOILERS[:2] + SPOILERS[4:], ids=lambda f: f.__name__.strip("_"))
def test_an_unusable_rally_is_left_out(fixture, spoil):
    the_rally = spoil(rally(fixture, "en"), fixture)
    doc = assemble_module_story(
        module_ctx(fixture, "en"), chapter_sources(fixture, "en"), the_rally
    )
    assert [c["covers"]["unit_number"] for c in doc["chapters"]] == list(LESSONS)
    assert validate_module_story(doc).ok


def test_a_rally_without_a_quiz_unit_is_left_out(fixture):
    sources = [s for s in chapter_sources(fixture, "en") if s.unit.role == "lesson"]
    doc = assemble_module_story(module_ctx(fixture, "en"), sources, rally(fixture, "en"))
    assert len(doc["chapters"]) == 3


def test_a_module_with_no_ready_lesson_is_never_publishable(fixture):
    sources = [ChapterSource(s.unit, None) for s in chapter_sources(fixture, "fr")]
    doc = assemble_module_story(module_ctx(fixture, "fr"), sources)
    assert [c["covers"]["status"] for c in doc["chapters"]] == ["unavailable"] * 3
    report = validate_module_story(doc)
    assert not report.ok
    assert {e.code for e in report.errors} == {"missing_objectives", "too_few_questions"}
    assert "missing_minigame" in {w.code for w in report.warnings}
    assert doc["checks"]["predicted_typical"]["points"] == 0


def test_a_one_lesson_module_is_its_only_chapter(fixture):
    sources = chapter_sources(fixture, "en")[:1]
    doc = assemble_module_story(module_ctx(fixture, "en"), sources)
    assert len(doc["chapters"]) == 1
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


def test_the_rally_covers_the_last_quiz_unit(fixture):
    sources = chapter_sources(fixture, "fr")
    unit = sources[3].unit  # the case study becomes a second quiz unit, before 1.5
    sources[3] = ChapterSource(
        StoryUnit(unit.module_unit_id, "1.4", "quiz", 3, "quiz_checkpoint", unit.title), None
    )
    doc = assemble_module_story(module_ctx(fixture, "fr"), sources, rally(fixture, "fr"))
    assert [c["covers"]["unit_number"] for c in doc["chapters"]] == ["1.1", "1.2", "1.3", "1.5"]


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
    rng.shuffle(pool)
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
            if state != "missing" and pool:
                doc = copy.deepcopy(pool.pop())
                doc["id"] = repair.story_slug(unit.module_unit_id, language)
                if state == "old":
                    doc.pop("sira_builder")
                elif state == "foreign":
                    doc["languages"] = {"target": "fr" if language == "en" else "en"}
        sources.append(ChapterSource(unit, doc))
    the_rally = None
    quizzes = [s.unit for s in sources if s.unit.role == "quiz_checkpoint"]
    if quizzes and rng.random() < 0.7:
        the_rally = copy.deepcopy(fixture["rally"][language])
        the_rally["id"] = repair.story_slug(quizzes[-1].module_unit_id, language)
    ctx = ModuleStoryContext(
        module_id=uuid.UUID(int=rng.getrandbits(128)),
        language=language,
        module_number=rng.randint(0, 12),
        module_title=rng.choice([{"en": "M", "fr": "M fr"}, {"fr": "Seulement"}, {}]),
        course_title=rng.choice([{"en": "C", "fr": "C"}, {}]),
        previous_module=rng.choice([None, (1, {"en": "Before", "fr": "Avant"})]),
        is_kids=rng.random() < 0.5,
        bible=StoryBible.of(fixture["bible"]),
    )
    return ctx, sources, the_rally


@pytest.mark.parametrize("seed", range(40))
def test_any_roster_assembles_into_a_sound_story(fixture, seed):
    rng = random.Random(seed)
    ctx, sources, the_rally = random_roster(rng, fixture)
    before = copy.deepcopy([s.doc for s in sources] + [the_rally])

    doc = assemble_module_story(ctx, sources, the_rally)

    assert [s.doc for s in sources] + [the_rally] == before
    again = assemble_module_story(ctx, sources, the_rally)
    assert json.dumps(again, ensure_ascii=False) == json.dumps(doc, ensure_ascii=False)
    lessons = [s for s in sources if s.unit.role == "lesson"]
    rally_told = the_rally is not None
    assert len(doc["chapters"]) == len(lessons) + rally_told
    for chapter, source in zip(doc["chapters"], lessons, strict=False):
        assert chapter["covers"]["module_unit_id"] == str(source.unit.module_unit_id)
        assert chapter["covers"]["completes_unit"] == (chapter["covers"]["status"] == "ready")
    check_ids_unique(doc)
    check_references_resolve(doc)
    rally_source = None
    if rally_told:
        last_quiz = [s.unit for s in sources if s.unit.role == "quiz_checkpoint"][-1]
        rally_source = ChapterSource(last_quiz, the_rally)
    check_no_text_changed(doc, sources, rally_source)

    report = validate_module_story(doc)
    ready = sum(c["covers"]["status"] in ("ready", "checkpoint") for c in doc["chapters"])
    if ready:
        assert report.ok, [e.model_dump() for e in report.errors]
        assert sum(c["covers"]["max_points"] for c in doc["chapters"]) == (report.checks.max_points)
    else:
        # No lesson told (the service never assembles a module without one).
        assert {e.code for e in report.errors} <= {
            "missing_objectives",
            "missing_minigame",
            "missing_chapters",
            "too_few_questions",
        }


# --------------------------------------------------------------------------
# The assembler's own edits never join runs of questions (review of #2678)
# --------------------------------------------------------------------------


def _say(doc: dict[str, Any], en: str, fr: str) -> dict[str, Any]:
    """A ``say`` line of ``doc``'s first speaker, with these words."""
    first = next(
        s for sc in doc["chapters"][0]["scenes"] for s in sc["steps"] if s["type"] == "say"
    )
    return {**{k: v for k, v in first.items() if k not in ("en", "fr")}, "en": en, "fr": fr}


def _asks_only_in_scene_two(doc: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    """Every ask of ``doc`` moved into its second scene, right after its concept card."""
    scenes = doc["chapters"][0]["scenes"]
    for scene in scenes:
        scene["steps"] = [s for s in scene["steps"] if s["type"] != "ask"]
    second = scenes[1]["steps"]
    card = next(i for i, s in enumerate(second) if s["type"] == "concept") + 1
    second[card:card] = steps


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_retold_line_between_two_runs_of_questions_stays(fixture, language):
    """The reviewers' repro: dropping the retold line would join q4 q5 | q6 x1."""
    sources = chapter_sources(fixture, language)
    first = next(s.doc for s in sources if s.unit.unit_number == "1.1")
    second = next(s.doc for s in sources if s.unit.unit_number == "1.2")
    line = _say(first, "Great thinking, {child}, keep going!", "Bien pensé, {child}, continue !")
    first["chapters"][0]["scenes"][0]["steps"].insert(2, copy.deepcopy(line))
    _asks_only_in_scene_two(
        second,
        [
            {"type": "ask", "ref": "q4"},
            {"type": "ask", "ref": "q5"},
            copy.deepcopy(line),
            {"type": "ask", "ref": "q6"},
            {"type": "ask", "ref": "x1"},
        ],
    )
    for doc in (first, second):
        assert repair.publishable(
            validate_story_course(StoryCourse.model_validate(doc), generated=True), doc
        ).ok

    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))

    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    kept = [s for s in chapter_steps(doc["chapters"][1]) if s.get("en") == line["en"]]
    assert len(kept) == 1 and kept[0]["retold"] is True
    # Not a separator anywhere else: told again, it is still left out.
    assert "retold" not in next(
        s for s in chapter_steps(doc["chapters"][0]) if s.get("en") == line["en"]
    )


@pytest.mark.parametrize("language", LANGUAGES)
def test_short_praise_with_a_name_is_never_a_retold_line(fixture, language):
    """'Bravo, {child} !' is as short as 'Bravo !': it may come back in any chapter."""
    sources = chapter_sources(fixture, language)
    for source in sources[:3]:
        source.doc["chapters"][0]["scenes"][0]["steps"].insert(
            1, _say(source.doc, "Well done, {child}!", "Bravo, {child} !")
        )
    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))
    praise = [s for s in all_steps(doc) if s.get("en") == "Well done, {child}!"]
    assert len(praise) == 3 and not any("retold" in s for s in praise)
    assert validate_module_story(doc).ok
    assert repair.repeat_keys(praise[0]) == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_copy_whose_situation_card_separates_two_runs_is_kept(fixture, language):
    """Dropping the copy and its situation card would join q5 q6 | q99 x1 q4."""
    sources = chapter_sources(fixture, language)
    first = next(s.doc for s in sources if s.unit.unit_number == "1.1")
    second = next(s.doc for s in sources if s.unit.unit_number == "1.2")
    copied = copy.deepcopy(next(q for q in first["questions"] if q["id"] == "q2"))
    copied["id"] = "q99"
    copied["stem"] = dict(copied["prompt"])  # a long stem: shown on a situation card
    second["questions"].append(copied)
    second["misconceptions"] += [
        m
        for m in first["misconceptions"]
        if m["id"] in {c.get("misconception") for c in copied["choices"]}
        and m["id"] not in {x["id"] for x in second["misconceptions"]}
    ]
    second["checks"]["max_points"] += 2
    situation = {
        "type": "concept",
        "id": repair.situation_step_id("q99"),
        "title": {"en": "The situation", "fr": "La situation"},
        "en": [copied["stem"]["en"]],
        "fr": [copied["stem"]["fr"]],
    }
    _asks_only_in_scene_two(
        second,
        [
            {"type": "ask", "ref": "q5"},
            {"type": "ask", "ref": "q6"},
            situation,
            {"type": "ask", "ref": "q99"},
            {"type": "ask", "ref": "x1"},
            {"type": "ask", "ref": "q4"},
        ],
    )
    assert repair.publishable(
        validate_story_course(StoryCourse.model_validate(second), generated=True), second
    ).ok

    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))

    assert "u1_2-q99" in {q["id"] for q in doc["questions"]}
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_run_too_long_in_a_chapter_is_capped_with_its_points(fixture, language):
    """The backstop: a chapter that slipped through with four asks in a row."""
    sources = chapter_sources(fixture, language)
    second = next(s.doc for s in sources if s.unit.unit_number == "1.2")
    _asks_only_in_scene_two(
        second,
        [{"type": "ask", "ref": ref} for ref in ("q4", "q5", "q6", "x1")],
    )
    doc = assemble_module_story(module_ctx(fixture, language), sources, rally(fixture, language))

    assert "u1_2-x1" not in {q["id"] for q in doc["questions"]}
    report = validate_module_story(doc)
    assert report.ok, [e.model_dump() for e in report.errors]
    covers = {c["covers"]["unit_number"]: c["covers"] for c in doc["chapters"]}
    assert covers["1.2"]["max_points"] == second["checks"]["max_points"] - 2
    assert sum(c["max_points"] for c in covers.values()) == report.checks.max_points
