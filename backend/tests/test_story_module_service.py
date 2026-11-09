"""The module story, end to end on a real PostgreSQL database with a fake model.

A module of six units — four lessons, one quiz unit covering all of them and
one case study — runs through :class:`ModuleStoryService` exactly as the Celery
task runs it: the setup, one ``AsyncSession`` per chapter under a concurrency
cap, the lessons and the quiz generated when missing (by fakes that write real
``generated_content`` rows), the chapters made by the real per-lesson pipeline
from fixture spines, and the module row assembled and stored. Then every way
the story can go stale, or must not.

Needs a PostgreSQL server (``DATABASE_URL``; CI has one): a scratch database
holding only the story tables is created for the module and dropped after.
Skipped without a server.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.usage_context import current_ai_context
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_bible import StoryCourseBible
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import find_bible
from app.domain.services.story_module_assembly import MODULE_ASSEMBLER_VERSION, module_story_slug
from app.domain.services.story_module_service import (
    ChapterGenerationFailed,
    ModuleStoryService,
    NoStoryContent,
    find_module_story,
    load_story_units,
    module_story_is_fresh,
    roster_digest,
    story_dispatch_key,
)
from tests._story_db import create_tables, scratch_database, story_tables
from tests.test_story_from_lesson import covering_quiz, picking_spine

pytestmark = pytest.mark.asyncio(loop_scope="session")

FIXTURE = Path(__file__).parent / "fixtures" / "lesson_story_unit.json"
SENTINEL = "SENTINEL-OPTION-MISCONCEPTION"
LESSONS = ["1.1", "1.2", "1.5", "1.6"]

#: (unit_number, unit_type, order_index, title_en, title_fr)
ROSTER = [
    ("1.1", "lesson", 0, "How malaria spreads", "Comment le paludisme se transmet"),
    ("1.2", "lesson", 1, "Preventing malaria in children", "Prévenir le paludisme"),
    ("1.3", "quiz", 2, "Quiz: malaria basics", "Quiz : les bases du paludisme"),
    ("1.4", "case-study", 3, "A fever in Kaya", "Une fièvre à Kaya"),
    ("1.5", "lesson", 4, "Treating simple malaria", "Traiter le paludisme simple"),
    ("1.6", None, 5, "Working with the community", "Travailler avec la communauté"),
]

_UNIT_RE = re.compile(r"chapter for unit (\S+) ")
_CANDIDATE_RE = re.compile(r"^\[(q\d+)\]( \(already asked\))? (.+)$", re.MULTILINE)


def rally_spine(raw: dict[str, Any], language: str, message: str) -> dict[str, Any]:
    """The rally's screenplay: the two candidates no lesson asked, as the prompt lists them."""
    home = "fr" if language == "en" else "en"
    target_quiz = covering_quiz(raw, language)["questions"]
    home_quiz = {q["id"]: q for q in covering_quiz(raw, home)["questions"]}
    by_stem = {q["question"]: q for q in target_quiz}
    candidates = [(ref, by_stem[stem]) for ref, marked, stem in _CANDIDATE_RE.findall(message)]
    fresh = [
        (ref, q)
        for (ref, q), (_r, marked, _s) in zip(
            candidates, _CANDIDATE_RE.findall(message), strict=True
        )
        if not marked
    ]
    picks = (fresh or candidates)[:2]
    derived, misconceptions = [], []
    for ref, question in picks:
        twin = home_quiz[question["id"]]
        distractors = []
        for index in range(len(question["options"])):
            if index == question["correct_answer"]:
                continue
            mid = f"m_rally_{question['id']}_{index}"
            misconceptions.append(
                {
                    "id": mid,
                    "en": f"Thinks option {index} is right.",
                    "fr": f"Pense que l'option {index} est juste.",
                }
            )
            distractors.append(
                {
                    "option": "abcd"[index],
                    "misconception": mid,
                    "hint": {"en": "Look again at the lesson.", "fr": "Relis la leçon."},
                }
            )
        derived.append(
            {
                "ref": ref,
                "objective": "o1",
                "prompt_home": twin["question"],
                "options_home": twin["options"],
                "explanation_home": twin.get("explanation", ""),
                "distractors": distractors,
            }
        )
    lesson = raw[language]["spine"]
    return {
        "chapter_title": {"en": "The district rally", "fr": "Le rallye du district"},
        "objectives": [{"id": "o1", "en": "Bring the module together", "fr": "Réunir le module"}],
        "misconceptions": [*misconceptions, *lesson["misconceptions"]],
        "scenes": [
            {
                "place": "meeting_room",
                "cast": ["mentor", "hero"],
                "steps": [
                    {
                        "type": "narrate",
                        "en": "Friday. The whole district team meets for the rally.",
                        "fr": "Vendredi. Toute l'équipe du district se réunit pour le rallye.",
                    },
                    {
                        "type": "say",
                        "who": "mentor",
                        "mood": "happy",
                        "en": "Two last challenges before we close the campaign.",
                        "fr": "Deux derniers défis avant de clore la campagne.",
                    },
                    {"type": "ask", "ref": picks[0][0]},
                ],
            },
            {
                "place": "field",
                "cast": ["friend", "hero"],
                "steps": [
                    {
                        "type": "say",
                        "who": "friend",
                        "mood": "think",
                        "en": "The last one is the hardest. Ready for it?",
                        "fr": "Le dernier est le plus dur. Tu es là ?",
                    },
                    *[{"type": "ask", "ref": ref} for ref, _q in picks[1:]],
                    {
                        "type": "say",
                        "who": "hero",
                        "mood": "happy",
                        "en": "Done! Every family in the district now knows what to do.",
                        "fr": "Fini ! Chaque famille du district sait maintenant quoi faire.",
                    },
                    {"type": "game"},
                    {"type": "photo", "ref": "E1"},
                ],
            },
        ],
        "derived": derived,
        "questions": [],
        "exercises": [lesson["exercises"][0] | {"objective": "o1"}],
        "minigame": lesson["minigame"],
        "__complete": True,
    }


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with scratch_database("story_module") as url:
        create_tables(url, story_tables())
        yield url


class Sessions:
    """``session_factory`` for the service that remembers every session it made."""

    def __init__(self, engine) -> None:
        self.maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        self.made: list[AsyncSession] = []

    def __call__(self) -> AsyncSession:
        session = self.maker()
        self.made.append(session)
        return session


@pytest.fixture
async def engine(database_url):
    engine = create_async_engine(database_url, pool_size=8, max_overflow=2)
    yield engine
    names = ", ".join(t.name for t in story_tables())
    async with engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {names} CASCADE"))
    await engine.dispose()


@pytest.fixture
def sessions(engine) -> Sessions:
    return Sessions(engine)


@pytest.fixture(autouse=True)
def assess():
    """The lesson's quality assessment is queued, never run."""
    with patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task") as task:
        yield task


# --------------------------------------------------------------------------
# Fakes
# --------------------------------------------------------------------------


class FakeClaude:
    """The spine model: the fixture spine, picking the covering quiz's 4 relevant MCQs.

    Knows each call's unit from the user message. Per unit it can fail, answer
    unreadable JSON, or be slow; ``soft_limit_on_call`` raises Celery's soft
    time limit on that call. Tracks the calls in flight and their maximum.
    """

    def __init__(
        self,
        raw: dict[str, Any],
        language: str,
        *,
        delay: float = 0.0,
        fail: dict[str, Exception] | None = None,
        unreadable: set[str] | None = None,
        soft_limit_on_call: int | None = None,
    ) -> None:
        self.raw, self.language = raw, language
        #: Units whose spine comes back revised (its first objective reworded).
        self.revised: set[str] = set()
        self.delay = delay
        self.fail = dict(fail or {})
        self.unreadable = set(unreadable or ())
        self.soft_limit_on_call = soft_limit_on_call
        self.calls: list[str] = []
        #: The course bible's and the rally's calls, apart from the chapters'.
        self.bible_calls = 0
        self.rally_calls = 0
        self.rally_answer: Any = None
        #: The course bible's answer: by default, the audience's default cast and places.
        self.bible_answer: dict[str, Any] = {}
        self.features: list[str | None] = []
        self.cancelled: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        if user.startswith("COURSE:"):
            self.bible_calls += 1
            return copy.deepcopy(self.bible_answer)
        if "screenplay of the RALLY" in user:
            self.rally_calls += 1
            if self.rally_answer is not None:
                return copy.deepcopy(self.rally_answer)
            return rally_spine(self.raw, self.language, user)
        unit = _UNIT_RE.search(user).group(1)
        self.calls.append(unit)
        self.features.append(current_ai_context().feature)
        number = len(self.calls)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if number == self.soft_limit_on_call:
                await asyncio.sleep(0.05)  # the others are well under way
                raise SoftTimeLimitExceeded()
            try:
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                self.cancelled.append(unit)
                raise
            if unit in self.fail:
                raise self.fail[unit]
            if unit in self.unreadable:
                return {"raw_response": "this is not JSON"}
            spine = picking_spine(self.raw, self.language)
            if "this unit has no quiz yet" in user:
                # Nothing to pick: the model asks only its own questions.
                spine["derived"] = []
                for scene in spine["scenes"]:
                    scene["steps"] = [
                        s
                        for s in scene["steps"]
                        if not (s["type"] == "ask" and str(s["ref"]).startswith("q"))
                    ]
            if unit in self.revised:
                objective = spine["objectives"][0]
                objective["en"] = (
                    "Explain how bed nets and seasonal chemoprevention protect children"
                )
                objective["fr"] = "Expliquer comment moustiquaires et chimioprévention protègent"
            return {**spine, "__complete": True}
        finally:
            self.in_flight -= 1


async def _unit_id(session: AsyncSession, module_id: uuid.UUID, unit_number: str) -> uuid.UUID:
    return (
        await session.execute(
            sa.select(ModuleUnit.id).where(
                ModuleUnit.module_id == module_id, ModuleUnit.unit_number == unit_number
            )
        )
    ).scalar_one()


class FakeLessonService:
    """Writes the fixture lesson as a real cached row, like the lesson service."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.calls: list[str] = []
        self.features: list[str | None] = []
        self.sessions: dict[str, AsyncSession] = {}

    async def get_or_generate_lesson(
        self, *, module_id, unit_id, language, country, level, session
    ):
        self.calls.append(unit_id)
        self.features.append(current_ai_context().feature)
        self.sessions[unit_id] = session
        row = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            module_unit_id=await _unit_id(session, module_id, unit_id),
            content_type="lesson",
            language=language,
            level=level,
            country_context=country,
            content=copy.deepcopy(self.raw[language]["lesson"]),
        )
        session.add(row)
        await session.commit()
        return SimpleNamespace(id=row.id)


def quiz_content(raw: dict[str, Any], language: str) -> dict[str, Any]:
    """The quiz unit's quiz, with a sentinel in every option_misconceptions slot."""
    content = covering_quiz(raw, language)
    for question in content["questions"]:
        question["option_misconceptions"] = [
            None if i == question["correct_answer"] else f"{SENTINEL}-{question['id']}-{i}"
            for i in range(len(question["options"]))
        ]
    return content


class FakeQuizService:
    """Writes the covering quiz as a real cached row, like the quiz service."""

    def __init__(self, raw: dict[str, Any], *, fail: Exception | None = None) -> None:
        self.raw = raw
        self.fail = fail
        self.calls: list[str] = []
        self.features: list[str | None] = []

    async def get_or_generate_quiz(
        self, module_id, unit_id, language, country, level, num_questions=None, *, session
    ):
        self.calls.append(unit_id)
        self.features.append(current_ai_context().feature)
        await asyncio.sleep(0.02)  # the other chapters queue up behind it
        if self.fail is not None:
            raise self.fail
        row = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            module_unit_id=await _unit_id(session, module_id, unit_id),
            content_type="quiz",
            language=language,
            level=level,
            country_context=country,
            content=quiz_content(self.raw, language),
        )
        session.add(row)
        await session.commit()
        return SimpleNamespace(id=row.id)


# --------------------------------------------------------------------------
# Seeding and reading
# --------------------------------------------------------------------------


@dataclass
class Seed:
    course_id: uuid.UUID
    module_id: uuid.UUID
    units: dict[str, uuid.UUID]


async def seed(
    sessions: Sessions,
    raw: dict[str, Any],
    language: str = "en",
    *,
    cached_lessons: tuple[str, ...] = ("1.1", "1.6"),
    cached_quiz: bool = False,
    roster: list[tuple[str, str | None, int, str, str]] = ROSTER,
) -> Seed:
    course_id, module_id = uuid.uuid4(), uuid.uuid4()
    units = {number: uuid.uuid4() for number, *_ in roster}
    async with sessions.maker() as session:
        session.add(
            Course(
                id=course_id,
                slug=f"course-{course_id.hex[:8]}",
                title_en="Public health",
                title_fr="Santé publique",
            )
        )
        await session.flush()
        session.add(
            Module(
                id=uuid.uuid4(),
                module_number=1,
                level=1,
                title_en="Getting started",
                title_fr="Pour commencer",
                course_id=course_id,
            )
        )
        session.add(
            Module(
                id=module_id,
                module_number=2,
                level=1,
                title_en="Malaria control",
                title_fr="Lutte contre le paludisme",
                course_id=course_id,
            )
        )
        await session.flush()
        for number, kind, order, title_en, title_fr in roster:
            session.add(
                ModuleUnit(
                    id=units[number],
                    module_id=module_id,
                    unit_number=number,
                    unit_type=kind,
                    order_index=order,
                    title_en=title_en,
                    title_fr=title_fr,
                )
            )
        await session.flush()
        for number in cached_lessons:
            session.add(_content_row(module_id, units[number], "lesson", language, raw))
        if cached_quiz:
            session.add(_content_row(module_id, units["1.3"], "quiz", language, raw))
        await session.commit()
    return Seed(course_id, module_id, units)


def _content_row(module_id, unit_id, content_type, language, raw) -> GeneratedContent:
    content = (
        copy.deepcopy(raw[language]["lesson"])
        if content_type == "lesson"
        else quiz_content(raw, language)
    )
    return GeneratedContent(
        id=uuid.uuid4(),
        module_id=module_id,
        module_unit_id=unit_id,
        content_type=content_type,
        language=language,
        level=1,
        country_context="CI",
        content=content,
    )


async def module_row(sessions: Sessions, seed: Seed, language: str = "en"):
    async with sessions.maker() as session:
        return await find_module_story(session, seed.module_id, language)


async def chapter_rows(sessions: Sessions, seed: Seed, language: str = "en"):
    async with sessions.maker() as session:
        rows = (
            await session.execute(
                sa.select(StoryCourseRecord).where(
                    StoryCourseRecord.module_unit_id.is_not(None),
                    StoryCourseRecord.language == language,
                )
            )
        ).scalars()
        by_id = {v: k for k, v in seed.units.items()}
        return {by_id[row.module_unit_id]: row for row in rows}


async def execute(sessions: Sessions, statement) -> None:
    async with sessions.maker() as session:
        await session.execute(statement)
        await session.commit()


def make_service(raw, language="en", **model_options):
    model = FakeClaude(raw, language, **model_options)
    lessons, quizzes = FakeLessonService(raw), FakeQuizService(raw)
    return ModuleStoryService(model, lessons, quizzes), model, lessons, quizzes


async def generate(service, seed: Seed, sessions: Sessions, language="en", **kwargs):
    return await service.get_or_generate_module_story(seed.module_id, language, sessions, **kwargs)


def statuses(record: StoryCourseRecord) -> list[str]:
    return [unit["status"] for unit in record.source_rows["units"]]


# --------------------------------------------------------------------------
# The first open, and the second
# --------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["en", "fr"])
async def test_the_first_open_makes_every_chapter_and_a_published_module_story(
    raw, sessions, assess, language
):
    seed_ = await seed(sessions, raw, language)
    service, model, lessons, quizzes = make_service(raw, language)

    record = await generate(service, seed_, sessions, language)

    # One screenplay call per lesson chapter, one for the course bible and one
    # for the rally; the missing lessons and the covering quiz generated once
    # each, under their own ledger features.
    assert sorted(model.calls) == LESSONS
    assert (model.bible_calls, model.rally_calls) == (1, 1)
    assert set(model.features) == {"story_generation"}
    assert sorted(lessons.calls) == ["1.2", "1.5"]
    assert set(lessons.features) == {"lesson_generation"}
    assert quizzes.calls == ["1.3"] and quizzes.features == ["quiz_generation"]
    dispatched = [call.kwargs["kwargs"]["content_id"] for call in assess.apply_async.call_args_list]
    assert len(dispatched) == 2  # the two generated lessons, as the lesson task does

    chapters = await chapter_rows(sessions, seed_, language)
    assert sorted(chapters) == LESSONS
    for number, chapter in chapters.items():
        assert chapter.status == "published" and chapter.is_valid, number
        assert chapter.content["sira_builder"] == repair.CHAPTER_BUILDER_VERSION
        assert chapter.source_quiz_content_id is not None  # the covering quiz unit's

    assert record.slug == module_story_slug(seed_.module_id, language)
    assert record.status == "published" and record.is_valid is True
    assert record.validation_report["errors"] == []
    assert (record.module_id, record.module_unit_id, record.language) == (
        seed_.module_id,
        None,
        language,
    )
    assert record.course_id == seed_.course_id
    assert record.source_lesson_content_id is None and record.source_quiz_content_id is None
    assert record.max_points == record.content["checks"]["max_points"] > 0
    assert record.content["module_story"]["assembler"] == MODULE_ASSEMBLER_VERSION
    assert record.content["module_story"]["module_id"] == str(seed_.module_id)

    # The manifest (C-3), unit by unit in teaching order, with the generator,
    # the bible and the rally it was made with.
    assert record.source_rows["assembler"] == MODULE_ASSEMBLER_VERSION
    assert record.source_rows["generator"] == repair.CHAPTER_BUILDER_VERSION
    async with sessions.maker() as session:
        bible = await find_bible(session, seed_.course_id)
    assert record.source_rows["bible"] == bible.digest == record.content["module_story"]["bible"]
    rally = record.source_rows["rally"]
    assert rally["status"] == "ready" and rally["doc"]["sira_chapter"]["kind"] == "rally"
    for chapter in chapters.values():
        assert chapter.content["sira_chapter"]["bible"] == bible.digest
    assert [chapters[n].content["sira_chapter"]["arc"] for n in LESSONS] == [
        "opens",
        "continues",
        "continues",
        "continues",
    ]
    assert record.content["cast"][0]["variants"]  # the bible's, with its looks
    units = record.source_rows["units"]
    assert [u["unit_number"] for u in units] == [r[0] for r in ROSTER]
    assert [u["role"] for u in units] == [
        "lesson",
        "lesson",
        "quiz_checkpoint",
        "case_checkpoint",
        "lesson",
        "lesson",
    ]
    assert statuses(record) == ["ready", "ready", "checkpoint", "checkpoint", "ready", "ready"]
    for entry in units:
        assert set(entry) == {
            "module_unit_id",
            "unit_number",
            "role",
            "status",
            "chapter_story_id",
            "chapter_updated_at",
        }
        if entry["role"] == "lesson":
            chapter = chapters[entry["unit_number"]]
            assert entry["chapter_story_id"] == str(chapter.id)
            assert entry["chapter_updated_at"] == chapter.updated_at.isoformat()
        else:
            assert entry["chapter_story_id"] is None and entry["chapter_updated_at"] is None
    async with sessions.maker() as session:
        assert record.source_units_digest == roster_digest(
            await load_story_units(session, seed_.module_id)
        )
        assert await module_story_is_fresh(session, record)

    # One chapter per lesson, then the rally for the quiz unit; none for the case study.
    covers = [c["covers"] for c in record.content["chapters"]]
    assert [c["unit_number"] for c in covers] == [*LESSONS, "1.3"]
    assert [c["completes_unit"] for c in covers] == [True, True, True, True, False]
    assert covers[-1]["rally"] is True and covers[-1]["role"] == "quiz_checkpoint"
    # Story points sum over the chapters.
    assert sum(c["max_points"] for c in covers) == record.max_points

    # option_misconceptions are prompt input only: never in a chapter or the module.
    for chapter in chapters.values():
        assert SENTINEL not in json.dumps(chapter.content, ensure_ascii=False)
    assert SENTINEL not in json.dumps(record.content, ensure_ascii=False)


class _UndeclaredMisconceptionsModel(FakeClaude):
    """A spine whose wrong options name misconception ids it never declared."""

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        spine = await super().generate_structured_content(system, user, content_type, max_retries)
        for entry in spine.get("derived", []):
            for n, item in enumerate(entry.get("distractors", [])):
                item["misconception"] = f"m_never_declared_{entry['ref']}_{n}"
        return spine


async def test_option_misconceptions_never_fill_a_gap_the_model_left(raw, sessions):
    """The fallback path: every wrong option of every picked question names an
    undeclared id. Each is declared from its wrong option, never from the
    covering quiz's option_misconceptions (sentinels): not in the chapters,
    not in the module story the API serves."""
    seed_ = await seed(sessions, raw, cached_quiz=True)
    model = _UndeclaredMisconceptionsModel(raw, "en")
    service = ModuleStoryService(model, FakeLessonService(raw), FakeQuizService(raw))

    record = await generate(service, seed_, sessions)

    chapters = await chapter_rows(sessions, seed_)
    assert sorted(chapters) == LESSONS
    for chapter in chapters.values():
        assert SENTINEL not in json.dumps(chapter.content, ensure_ascii=False)
    assert SENTINEL not in json.dumps(record.content, ensure_ascii=False)
    assert any(
        m["id"].startswith("u1_1-m_never_declared") for m in record.content["misconceptions"]
    )
    assert record.status == "published" and record.is_valid
    assert all(c.status == "published" and c.is_valid for c in chapters.values())
    assert sorted(model.calls) == LESSONS  # published at once: nothing to repair


async def test_the_second_open_calls_nothing_and_changes_nothing(raw, sessions):
    seed_ = await seed(sessions, raw)
    service, model, lessons, quizzes = make_service(raw)
    first = await generate(service, seed_, sessions)
    calls = (len(model.calls), len(lessons.calls), len(quizzes.calls))

    again = await generate(service, seed_, sessions)

    assert (len(model.calls), len(lessons.calls), len(quizzes.calls)) == calls
    assert (model.bible_calls, model.rally_calls) == (1, 1)
    assert again.id == first.id and again.updated_at == first.updated_at


async def test_a_module_without_lessons_has_no_story(raw, sessions):
    roster = [r for r in ROSTER if r[1] not in ("lesson", None)]
    seed_ = await seed(sessions, raw, cached_lessons=(), roster=roster)
    service, model, *_ = make_service(raw)
    with pytest.raises(NoStoryContent):
        await generate(service, seed_, sessions)
    with pytest.raises(ValueError, match="not found"):
        await service.get_or_generate_module_story(uuid.uuid4(), "en", sessions)
    assert model.calls == []


async def test_the_dispatch_key_names_the_module():
    module_id = uuid.UUID(int=7)
    assert story_dispatch_key(module_id, "fr") == f"story_dispatch:module:{module_id}:fr"


# --------------------------------------------------------------------------
# Staleness: exactly what changed is paid for again
# --------------------------------------------------------------------------


async def _first(raw, sessions):
    seed_ = await seed(sessions, raw)
    service, model, lessons, quizzes = make_service(raw)
    record = await generate(service, seed_, sessions)
    model.calls.clear()
    lessons.calls.clear()
    quizzes.calls.clear()
    return seed_, service, model, lessons, quizzes, record


async def test_a_regenerated_lesson_remakes_only_its_chapter(raw, sessions):
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    await execute(
        sessions,
        sa.update(GeneratedContent)
        .where(
            GeneratedContent.module_unit_id == seed_.units["1.2"],
            GeneratedContent.content_type == "lesson",
        )
        .values(content_revision=2),
    )
    async with sessions.maker() as session:
        assert not await module_story_is_fresh(session, first)
    model.revised = {"1.2"}  # the new lesson gives a different chapter

    record = await generate(service, seed_, sessions)

    assert model.calls == ["1.2"]
    assert lessons.calls == [] and quizzes.calls == []
    assert record.id == first.id
    assert record.content["module_story"]["revision"] != first.content["module_story"]["revision"]
    assert record.status == "published"


async def test_a_lesson_edited_in_place_remakes_only_its_chapter(raw, sessions):
    seed_, service, model, *_ = await _first(raw, sessions)
    edited = copy.deepcopy(raw["en"]["lesson"])
    edited["introduction"] = "Corrected: " + edited["introduction"]
    await execute(
        sessions,
        sa.update(GeneratedContent)
        .where(
            GeneratedContent.module_unit_id == seed_.units["1.6"],
            GeneratedContent.content_type == "lesson",
        )
        .values(content=edited),
    )

    await generate(service, seed_, sessions)

    assert model.calls == ["1.6"]


async def test_an_edited_covering_quiz_remakes_every_chapter_it_covers(raw, sessions):
    seed_, service, model, lessons, quizzes, _ = await _first(raw, sessions)
    edited = quiz_content(raw, "en")
    edited["questions"][0]["explanation"] = "Corrected explanation."
    await execute(
        sessions,
        sa.update(GeneratedContent)
        .where(GeneratedContent.module_unit_id == seed_.units["1.3"])
        .values(content=edited),
    )

    await generate(service, seed_, sessions)

    assert sorted(model.calls) == LESSONS
    assert lessons.calls == [] and quizzes.calls == []


async def test_a_renamed_unit_only_re_merges(raw, sessions):
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    rallies = model.rally_calls
    await execute(
        sessions,
        sa.update(ModuleUnit)
        .where(ModuleUnit.id == seed_.units["1.2"])
        .values(title_en="Nets, tests and seasonal doses"),
    )
    async with sessions.maker() as session:
        assert not await module_story_is_fresh(session, first)

    record = await generate(service, seed_, sessions)

    assert model.calls == [] and lessons.calls == [] and quizzes.calls == []
    assert model.rally_calls == rallies  # the rally is reused too
    assert record.id == first.id
    assert record.source_units_digest != first.source_units_digest
    assert record.content["chapters"][1]["title"]["en"] == "1.2 · Nets, tests and seasonal doses"
    async with sessions.maker() as session:
        assert await module_story_is_fresh(session, record)


async def test_an_added_quiz_unit_only_re_merges(raw, sessions):
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    async with sessions.maker() as session:
        session.add(
            ModuleUnit(
                id=uuid.uuid4(),
                module_id=seed_.module_id,
                unit_number="1.7",
                unit_type="quiz",
                order_index=6,
                title_en="Final quiz",
                title_fr="Quiz final",
            )
        )
        await session.commit()

    record = await generate(service, seed_, sessions)

    # 1.6 is now covered by 1.7, which has no quiz: its chapter, built from
    # 1.3's quiz, is still fresh — no chapter is generated or paid for. The
    # rally is told for the module's last quiz unit, now 1.7: it is made again.
    assert model.calls == [] and lessons.calls == [] and quizzes.calls == []
    assert model.rally_calls == 2
    assert [c["covers"]["unit_number"] for c in record.content["chapters"]][-1] == "1.7"
    assert statuses(record)[-1] == "checkpoint"
    assert record.status == "published"


class TwoExtraQuestions(FakeClaude):
    """The spine with a second extra question: a chapter with no quiz still has two."""

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        spine = await super().generate_structured_content(system, user, content_type, max_retries)
        if not spine.get("questions"):
            return spine  # the bible or the rally
        extra = copy.deepcopy(spine["questions"][0])
        extra["id"] = "x2"
        extra["prompt"] = {
            "en": "How many nights a week should a child sleep under a net? (number only)",
            "fr": "Combien de nuits par semaine sous la moustiquaire ? (nombre seul)",
        }
        extra["answer"] = "7"
        extra["traps"] = []
        spine["questions"].append(extra)
        # Asked right after the second concept card, as the model places it.
        steps = spine["scenes"][1]["steps"]
        card = next(i for i, s in enumerate(steps) if s["type"] == "concept")
        steps.insert(card + 1, {"type": "ask", "ref": "x2"})
        return spine


async def test_a_quiz_generated_by_the_run_remakes_the_fresh_chapters_it_covers(raw, sessions):
    """The module story a run writes is fresh, even when the run made a covering quiz.

    A lessons-only module's chapters are built with no quiz. A lesson and a
    quiz unit covering every lesson are then added: only the new lesson's
    chapter is stale, but making it generates the quiz, which makes the two
    older chapters stale too. They are remade in the same run, so the next
    open serves the story without another wait.
    """
    roster = [r for r in ROSTER if r[0] in ("1.1", "1.2")]
    seed_ = await seed(sessions, raw, cached_lessons=("1.1", "1.2"), roster=roster)
    model = TwoExtraQuestions(raw, "en")
    lessons, quizzes = FakeLessonService(raw), FakeQuizService(raw)
    service = ModuleStoryService(model, lessons, quizzes)
    first = await generate(service, seed_, sessions)
    assert first.status == "published"
    assert sorted(model.calls) == ["1.1", "1.2"] and quizzes.calls == []
    model.calls.clear()
    async with sessions.maker() as session:
        for number, kind, order in (("1.3", "lesson", 2), ("1.4", "quiz", 3)):
            seed_.units[number] = uuid.uuid4()
            session.add(
                ModuleUnit(
                    id=seed_.units[number],
                    module_id=seed_.module_id,
                    unit_number=number,
                    unit_type=kind,
                    order_index=order,
                    title_en=f"Unit {number}",
                    title_fr=f"Unité {number}",
                )
            )
        await session.commit()

    record = await generate(service, seed_, sessions)

    assert lessons.calls == ["1.3"] and quizzes.calls == ["1.4"]
    # 1.3 (the quiz is generated for it) and 1.2 (no longer the last lesson: the
    # rally now solves the mission), then 1.1 from the new quiz.
    assert sorted(model.calls[:2]) == ["1.2", "1.3"] and model.calls[2:] == ["1.1"]
    assert record.status == "published"
    async with sessions.maker() as session:
        assert await module_story_is_fresh(session, record)
    chapters = await chapter_rows(sessions, seed_)
    for number in ("1.1", "1.2", "1.3"):
        derived = [q for q in chapters[number].content["questions"] if "derived_from" in q]
        assert derived and {q["derived_from"]["quiz_unit"] for q in derived} == {"1.4"}

    model.calls.clear()
    again = await generate(service, seed_, sessions)
    assert model.calls == [] and quizzes.calls == ["1.4"]
    assert again.updated_at == record.updated_at


async def test_an_own_quiz_on_a_lesson_unit_changes_nothing(raw, sessions):
    """The offline download creates one per unit; chapters never read it."""
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    async with sessions.maker() as session:
        session.add(_content_row(seed_.module_id, seed_.units["1.1"], "quiz", "en", raw))
        await session.commit()
        assert await module_story_is_fresh(session, first)

    record = await generate(service, seed_, sessions)

    assert model.calls == [] and quizzes.calls == []
    assert record.updated_at == first.updated_at


async def test_a_new_assembler_version_only_re_merges(raw, sessions):
    seed_, service, model, _, _, first = await _first(raw, sessions)
    await execute(
        sessions,
        sa.update(StoryCourseRecord)
        .where(StoryCourseRecord.id == first.id)
        .values(source_rows={**first.source_rows, "assembler": MODULE_ASSEMBLER_VERSION - 1}),
    )

    record = await generate(service, seed_, sessions)

    assert model.calls == []
    assert record.source_rows["assembler"] == MODULE_ASSEMBLER_VERSION


async def test_force_regenerate_remakes_every_chapter_but_no_lesson_or_quiz(raw, sessions):
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)

    record = await generate(service, seed_, sessions, force_regenerate=True)

    assert sorted(model.calls) == LESSONS
    assert lessons.calls == [] and quizzes.calls == []
    assert record.id == first.id and record.status == "published"


# --------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------


async def test_a_failed_chapter_writes_no_module_story_and_keeps_the_others(raw, sessions):
    seed_ = await seed(sessions, raw)
    service, model, lessons, quizzes = make_service(
        raw, fail={"1.5": RuntimeError("provider down")}
    )

    with pytest.raises(ChapterGenerationFailed) as failed:
        await generate(service, seed_, sessions)

    assert failed.value.failed_units == ["1.5"]
    assert "provider down" in failed.value.errors["1.5"]
    assert await module_row(sessions, seed_) is None
    assert sorted(await chapter_rows(sessions, seed_)) == ["1.1", "1.2", "1.6"]

    # The next open makes only the failed chapter; its lesson is already there.
    service2, model2, lessons2, quizzes2 = make_service(raw)
    record = await generate(service2, seed_, sessions)
    assert model2.calls == ["1.5"]
    assert lessons2.calls == [] and quizzes2.calls == []
    assert record.status == "published"


async def test_a_failed_covering_quiz_fails_its_chapters_once(raw, sessions):
    seed_ = await seed(sessions, raw)
    service, model, _lessons, _ = make_service(raw)
    service.quiz_service = quizzes = FakeQuizService(raw, fail=RuntimeError("quiz failed"))

    with pytest.raises(ChapterGenerationFailed) as failed:
        await generate(service, seed_, sessions)

    assert failed.value.failed_units == LESSONS
    assert quizzes.calls == ["1.3"]  # tried once, not once per chapter
    assert model.calls == []  # no chapter is built without its quiz
    assert await module_row(sessions, seed_) is None


async def test_unpublishable_chapters_make_a_draft_module_story(raw, sessions):
    """The API answers 409 story_unavailable; the next open pays for nothing."""
    seed_ = await seed(sessions, raw)
    service, model, *_ = make_service(raw, unreadable=set(LESSONS))

    record = await generate(service, seed_, sessions)

    assert len(model.calls) == 4 * (1 + 2)  # each chapter spent its repair budget
    chapters = await chapter_rows(sessions, seed_)
    assert {c.status for c in chapters.values()} == {"draft"}
    assert record.status == "draft" and record.is_valid is False
    assert record.validation_report["errors"]
    assert statuses(record) == [
        "unavailable",
        "unavailable",
        "checkpoint",
        "checkpoint",
        "unavailable",
        "unavailable",
    ]
    assert not any(c["covers"]["completes_unit"] for c in record.content["chapters"])

    model.calls.clear()
    again = await generate(service, seed_, sessions)
    assert model.calls == [] and again.updated_at == record.updated_at


async def test_a_soft_time_limit_cancels_the_other_chapters_and_propagates(raw, sessions):
    seed_ = await seed(sessions, raw, cached_lessons=tuple(LESSONS), cached_quiz=True)
    service, model, *_ = make_service(raw, delay=30.0, soft_limit_on_call=2)

    with pytest.raises(SoftTimeLimitExceeded):
        await asyncio.wait_for(generate(service, seed_, sessions), timeout=10)

    assert len(model.calls) == 4  # all started (concurrency 6)
    assert len(model.cancelled) == 3  # every other chapter was cancelled, not awaited
    assert await chapter_rows(sessions, seed_) == {}
    assert await module_row(sessions, seed_) is None


# --------------------------------------------------------------------------
# Concurrency and sessions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(("concurrency", "expected"), [(2, 2), (6, 4)])
async def test_chapters_run_concurrently_up_to_the_cap(raw, sessions, concurrency, expected):
    seed_ = await seed(sessions, raw, cached_lessons=tuple(LESSONS), cached_quiz=True)
    model = FakeClaude(raw, "en", delay=0.2)
    service = ModuleStoryService(
        model, FakeLessonService(raw), FakeQuizService(raw), concurrency=concurrency
    )

    await generate(service, seed_, sessions)

    assert len(model.calls) == 4
    assert model.max_in_flight == expected


async def test_every_chapter_has_its_own_session(raw, sessions):
    seed_ = await seed(sessions, raw)
    service, _model, lessons, _ = make_service(raw, delay=0.05)
    used: dict[str, AsyncSession] = {}
    original = service.chapters.get_or_generate_unit_story

    async def spy(module_id, unit_id, language, session, **kwargs):
        used[unit_id] = session
        return await original(module_id, unit_id, language, session, **kwargs)

    service.chapters.get_or_generate_unit_story = spy

    await generate(service, seed_, sessions)

    assert sorted(used) == LESSONS
    assert len({id(s) for s in used.values()}) == 4
    setup, *chapter_sessions, rally, merge = sessions.made
    assert {id(s) for s in chapter_sessions} == {id(s) for s in used.values()}
    assert setup not in used.values() and merge not in used.values()
    assert rally not in used.values()
    # A missing lesson is generated in its own chapter's session.
    assert lessons.sessions["1.2"] is used["1.2"]
    assert lessons.sessions["1.5"] is used["1.5"]


# --------------------------------------------------------------------------
# Freshness and the roster
# --------------------------------------------------------------------------


async def test_module_story_freshness_is_four_queries_however_many_chapters(raw, sessions, engine):
    seed_, _service, _model, _lessons, _quizzes, record = await _first(raw, sessions)
    statements: list[str] = []

    def count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    sa.event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with sessions.maker() as session:
            assert await module_story_is_fresh(session, record)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", count)

    # The roster, the bible's digest, the four chapter rows, and one query of
    # all their sources.
    assert len(statements) == 4, statements
    assert "story_course_bibles" in statements[1]
    assert "generated_content" in statements[3]

    # A caller that has just read the roster (the API) passes it: two queries.
    statements.clear()
    async with sessions.maker() as session:
        units = await load_story_units(session, seed_.module_id)
    sa.event.listen(engine.sync_engine, "before_cursor_execute", count)
    try:
        async with sessions.maker() as session:
            assert await module_story_is_fresh(session, record, units=units)
            renamed = [replace(units[0], title={"en": "Renamed", "fr": "Renommé"}), *units[1:]]
            assert not await module_story_is_fresh(session, record, units=renamed)
    finally:
        sa.event.remove(engine.sync_engine, "before_cursor_execute", count)
    assert len(statements) == 3, statements
    assert not any("FROM module_units" in statement for statement in statements)


async def test_only_module_rows_are_judged_by_module_freshness(raw, sessions):
    seed_, *_rest, record = await _first(raw, sessions)
    chapters = await chapter_rows(sessions, seed_)
    async with sessions.maker() as session:
        assert not await module_story_is_fresh(session, chapters["1.1"])
        assert not await module_story_is_fresh(session, StoryCourseRecord(slug="authored"))
        assert await module_story_is_fresh(session, record)
    record.source_units_digest = "0" * 64
    async with sessions.maker() as session:
        assert not await module_story_is_fresh(session, record)


async def test_units_are_classified_as_the_completion_api_does(raw, sessions):
    roster = [
        ("1.10", "lesson", 0, "Ten", "Dix"),
        ("1.9", None, 0, "Nine", "Neuf"),
        ("1.2", "quiz", 2, "Quiz", "Quiz"),
        ("1.3", "case-study", 3, "Case", "Cas"),
        ("1.4", "scenario", 4, "Scenario", "Scénario"),
        ("1.5", "exercise", 5, "Unknown", "Inconnu"),
        ("1.6", "quiz", 6, "Really a case", ""),
    ]
    seed_ = await seed(sessions, raw, cached_lessons=(), roster=roster)
    async with sessions.maker() as session:
        session.add(
            GeneratedContent(
                id=uuid.uuid4(),
                module_id=seed_.module_id,
                module_unit_id=seed_.units["1.6"],
                content_type="case",
                language="fr",
                level=1,
                content={},
            )
        )
        await session.commit()
        units = await load_story_units(session, seed_.module_id)

    assert [(u.unit_number, u.role) for u in units] == [
        ("1.9", "lesson"),  # order_index ties sort by unit number, read naturally
        ("1.10", "lesson"),
        ("1.2", "quiz_checkpoint"),
        ("1.3", "case_checkpoint"),
        ("1.4", "case_checkpoint"),
        ("1.5", "quiz_checkpoint"),  # unknown types are quiz-gated
        ("1.6", "case_checkpoint"),  # mislabelled, holds case content (#2163)
    ]
    assert units[-1].title == {"en": "Really a case", "fr": "Really a case"}


async def test_the_roster_digest_is_sha256_of_the_canonical_roster():
    import hashlib

    from app.domain.services.story_module_assembly import StoryUnit

    unit = StoryUnit(
        module_unit_id=uuid.UUID(int=1),
        unit_number="1.1",
        unit_type="lesson",
        order_index=0,
        role="lesson",
        title={"en": "Nets", "fr": "Moustiquaires"},
    )
    canonical = json.dumps(
        [[str(uuid.UUID(int=1)), "1.1", 0, "lesson", "Nets", "Moustiquaires"]],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert roster_digest([unit]) == hashlib.sha256(canonical.encode()).hexdigest()
    renamed = StoryUnit(**{**unit.__dict__, "title": {"en": "Bed nets", "fr": "Moustiquaires"}})
    assert roster_digest([renamed]) != roster_digest([unit])


# --------------------------------------------------------------------------
# The screenplay generator (#2674): stories of the old generator and the bible
# --------------------------------------------------------------------------


async def test_a_story_of_the_old_generator_is_remade_on_next_access(raw, sessions):
    """Stored before #2674: a manifest without a generator, chapters of builder 2."""
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    rallies = model.rally_calls
    old_manifest = {
        k: v for k, v in first.source_rows.items() if k not in ("generator", "bible", "rally")
    }
    await execute(
        sessions,
        sa.update(StoryCourseRecord)
        .where(StoryCourseRecord.id == first.id)
        .values(source_rows={**old_manifest, "assembler": 1}),
    )
    chapters = await chapter_rows(sessions, seed_)
    for row in chapters.values():
        content = {k: v for k, v in row.content.items() if k != "sira_chapter"}
        await execute(
            sessions,
            sa.update(StoryCourseRecord)
            .where(StoryCourseRecord.id == row.id)
            .values(content={**content, "sira_builder": 2}),
        )
    async with sessions.maker() as session:
        stale = await find_module_story(session, seed_.module_id, "en")
        assert not await module_story_is_fresh(session, stale)

    record = await generate(service, seed_, sessions)

    assert sorted(model.calls) == LESSONS  # every chapter told again
    assert lessons.calls == [] and quizzes.calls == []  # its sources are unchanged
    assert model.bible_calls == 1  # the course keeps its bible
    assert model.rally_calls == rallies + 1  # chapters changed: the rally too
    assert record.id == first.id
    assert record.source_rows["generator"] == repair.CHAPTER_BUILDER_VERSION
    async with sessions.maker() as session:
        assert await module_story_is_fresh(session, record)


async def test_the_generator_marker_alone_makes_a_module_story_stale(raw, sessions):
    seed_, service, model, _, _, first = await _first(raw, sessions)
    await execute(
        sessions,
        sa.update(StoryCourseRecord)
        .where(StoryCourseRecord.id == first.id)
        .values(source_rows={**first.source_rows, "generator": repair.CHAPTER_BUILDER_VERSION - 1}),
    )
    async with sessions.maker() as session:
        stale = await find_module_story(session, seed_.module_id, "en")
        assert not await module_story_is_fresh(session, stale)

    record = await generate(service, seed_, sessions)

    # Its chapters are this generator's: only the module row is merged again.
    assert model.calls == []
    assert record.source_rows["generator"] == repair.CHAPTER_BUILDER_VERSION


async def test_a_replaced_bible_remakes_every_chapter_with_one_call(raw, sessions):
    seed_, service, model, lessons, quizzes, first = await _first(raw, sessions)
    rallies = model.rally_calls
    await execute(sessions, sa.delete(StoryCourseBible))
    async with sessions.maker() as session:
        assert not await module_story_is_fresh(session, first)
    # Another bible: the office is drawn differently.
    model.bible_answer = {
        "places": [
            {
                "id": "desk",
                "title": {"en": "The office", "fr": "Le bureau"},
                "look": "a bright district office with a green wall and a big map",
            }
        ]
    }

    record = await generate(service, seed_, sessions)

    assert model.bible_calls == 2  # a new bible, once
    assert sorted(model.calls) == LESSONS
    assert model.rally_calls == rallies + 1
    async with sessions.maker() as session:
        bible = await find_bible(session, seed_.course_id)
        assert await module_story_is_fresh(session, record)
    assert record.source_rows["bible"] == bible.digest
    chapters = await chapter_rows(sessions, seed_)
    assert {row.content["sira_chapter"]["bible"] for row in chapters.values()} == {bible.digest}


async def test_two_modules_of_a_course_share_one_bible(raw, sessions):
    """The second module's story reuses the course's bible: same cast and places."""
    seed_, service, model, *_rest, first = await _first(raw, sessions)
    async with sessions.maker() as session:
        other_module = uuid.uuid4()
        session.add(
            Module(
                id=other_module,
                module_number=3,
                level=1,
                title_en="Malaria treatment",
                title_fr="Traitement du paludisme",
                course_id=seed_.course_id,
            )
        )
        await session.flush()
        unit_id = uuid.uuid4()
        session.add(
            ModuleUnit(
                id=unit_id,
                module_id=other_module,
                unit_number="3.1",
                unit_type="lesson",
                order_index=0,
                title_en="Treating simple malaria",
                title_fr="Traiter le paludisme simple",
            )
        )
        session.add(_content_row(other_module, unit_id, "lesson", "en", raw))
        await session.commit()

    second = await service.get_or_generate_module_story(other_module, "en", sessions)

    assert model.bible_calls == 1
    assert second.content["cast"] == first.content["cast"]
    assert second.content["places"] == first.content["places"]
    assert second.source_rows["bible"] == first.source_rows["bible"]
    # A one-lesson module without a quiz unit: its only chapter sets and solves the mission.
    async with sessions.maker() as session:
        row = (
            await session.execute(
                sa.select(StoryCourseRecord).where(StoryCourseRecord.module_unit_id == unit_id)
            )
        ).scalar_one()
    assert row.content["sira_chapter"]["arc"] == "opens_closes"
    assert "rally" not in second.source_rows
