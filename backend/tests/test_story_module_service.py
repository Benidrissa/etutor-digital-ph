"""The module story v4 (#2680), end to end on a real PostgreSQL database, fake model.

The kids biology module of ``fixtures/story_screenplay_module.json`` — three
lessons, a case study and a quiz unit — runs through
:class:`ModuleStoryService` exactly as the Celery task runs it: the prep (the
course bible while the lessons and the quiz are made by fakes that write real
``generated_content`` rows), the episode plan, the practice packs (concurrent),
the chapters told one after another, the rally, and the module row. Then
every way the story can go stale, or must not, and every way a run can stop.

Needs a PostgreSQL server (``DATABASE_URL``; CI has one): a scratch database
holding only the story tables is created for the module and dropped after.
Skipped without a server.
"""

from __future__ import annotations

import asyncio
import copy
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.models.story_module_plan import StoryModulePlan
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import StoryProviderUnavailable, find_bible
from app.domain.services.story_module_assembly import MODULE_ASSEMBLER_VERSION
from app.domain.services.story_module_service import (
    ASSEMBLY_FAILURE_CAP,
    CHAPTER_FAILURE_CAP,
    ChapterGenerationFailed,
    ModuleStoryService,
    NoStoryContent,
    StoryDeadlineReached,
    find_module_story,
    live_figures,
    module_story_is_fresh,
)
from app.domain.services.story_plan import DEFAULTED, DEFAULTED_KEPT
from tests._story_db import create_tables, scratch_database, story_tables
from tests.test_story_screenplay_module import (
    data,
    lesson_content,
    pack,
    plan_answer,
    quiz_questions,
    story_answer,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

LANGUAGE = "fr"
LESSONS = ("1.1", "1.2", "1.3")
_STORY_UNIT_RE = re.compile(r"the IDEAS of lesson (\S+) into the story")
_PACK_UNIT_RE = re.compile(r"\(lesson (\S+)\) of the episode")


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with scratch_database("story_module") as url:
        create_tables(url, story_tables())
        yield url


class Sessions:
    """``session_factory`` for the service, on an engine made on the test's loop."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = create_async_engine(url, pool_size=8, max_overflow=2)
        self.maker = async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    def __call__(self) -> AsyncSession:
        return self.maker()


@pytest.fixture
async def sessions(database_url):
    made = Sessions(database_url)
    yield made
    names = ", ".join(t.name for t in story_tables())
    async with made.engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {names} CASCADE"))
    await made.engine.dispose()


@pytest.fixture(autouse=True)
def assess():
    """The lesson's quality assessment is queued, never run."""
    with patch("app.tasks.quality_assessment.assess_and_regenerate_unit_task") as task:
        yield task


# --------------------------------------------------------------------------
# The fake model: answers the bible, the plan, the packs and the stories
# --------------------------------------------------------------------------


class FakeModel:
    """Knows each call's kind and chapter from its message; records the order of calls.

    ``events`` holds ``(start|end, kind, unit)`` in the order they happened,
    so a test can see what ran before, after or alongside what.
    ``unreadable`` makes a chapter's story calls answer junk; ``broken``
    makes a call raise.
    """

    def __init__(self, *, delay: float = 0.01, language: str = LANGUAGE) -> None:
        self.delay = delay
        self.language = language
        self.events: list[tuple[str, str, str]] = []
        self.calls: list[tuple[str, str]] = []
        self.messages: dict[tuple[str, str], list[str]] = {}
        self.unreadable: set[tuple[str, str]] = set()
        self.broken: dict[tuple[str, str], Exception] = {}
        self.plan = plan_answer()
        self._model = "fake-model"
        self.in_flight = 0
        self.cancelled: list[tuple[str, str]] = []

    @staticmethod
    def kind_of(user: str) -> tuple[str, str]:
        if user.startswith("COURSE:"):
            return "bible", ""
        if user.startswith("REQUEST: plan the episode"):
            return "plan", ""
        if user.startswith("REQUEST: write the practice items of the RALLY"):
            return "pack", "rally"
        if user.startswith("REQUEST: write the practice items"):
            return "pack", _PACK_UNIT_RE.search(user).group(1)
        if user.startswith("REQUEST: write the RALLY"):
            return "story", "rally"
        return "story", _STORY_UNIT_RE.search(user).group(1)

    def count(self, kind: str, unit: str | None = None) -> int:
        return sum(1 for k, u in self.calls if k == kind and (unit is None or u == unit))

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        kind, unit = self.kind_of(user)
        self.calls.append((kind, unit))
        self.messages.setdefault((kind, unit), []).append(user)
        self.events.append(("start", kind, unit))
        self.in_flight += 1
        try:
            try:
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                self.cancelled.append((kind, unit))
                raise
            if (kind, unit) in self.broken:
                raise self.broken[(kind, unit)]
            if (kind, unit) in self.unreadable:
                return {"raw_response": "not JSON"}
            if kind == "bible":
                return copy.deepcopy(data()["bible"])
            if kind == "plan":
                return {**copy.deepcopy(self.plan), "__complete": True}
            if kind == "pack":
                return {**pack(unit, self.language), "__complete": True}
            return story_answer(unit)
        finally:
            self.in_flight -= 1
            self.events.append(("end", kind, unit))


async def _unit_id(session: AsyncSession, module_id: uuid.UUID, number: str) -> uuid.UUID:
    return (
        await session.execute(
            sa.select(ModuleUnit.id).where(
                ModuleUnit.module_id == module_id, ModuleUnit.unit_number == number
            )
        )
    ).scalar_one()


class FakeLessonService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_or_generate_lesson(
        self, *, module_id, unit_id, language, country, level, session
    ):
        self.calls.append(unit_id)
        row = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            module_unit_id=await _unit_id(session, module_id, unit_id),
            content_type="lesson",
            language=language,
            level=level,
            country_context=country,
            content=lesson_content(unit_id, language),
        )
        session.add(row)
        await session.commit()
        return SimpleNamespace(id=row.id)


class FakeQuizService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_or_generate_quiz(
        self, module_id, unit_id, language, country, level, num_questions=None, *, session
    ):
        self.calls.append(unit_id)
        row = GeneratedContent(
            id=uuid.uuid4(),
            module_id=module_id,
            module_unit_id=await _unit_id(session, module_id, unit_id),
            content_type="quiz",
            language=language,
            level=level,
            country_context=country,
            content={"questions": quiz_questions(language)},
        )
        session.add(row)
        await session.commit()
        return SimpleNamespace(id=row.id)


@dataclass
class Seed:
    course_id: uuid.UUID
    module_id: uuid.UUID
    units: dict[str, uuid.UUID]


async def seed(sessions: Sessions, *, cached: bool = True, language: str = LANGUAGE) -> Seed:
    course_id, module_id = uuid.uuid4(), uuid.uuid4()
    units = {u["unit_number"]: uuid.uuid4() for u in data()["units"]}
    async with sessions.maker() as session:
        session.add(
            Course(
                id=course_id,
                slug=f"course-{course_id.hex[:8]}",
                title_en=data()["course"]["title"]["en"],
                title_fr=data()["course"]["title"]["fr"],
            )
        )
        await session.flush()
        session.add(
            Module(
                id=module_id,
                module_number=uuid.uuid4().int % 1_000_000 + 10,
                level=1,
                title_en=data()["module"]["module_title"]["en"],
                title_fr=data()["module"]["module_title"]["fr"],
                course_id=course_id,
            )
        )
        await session.flush()
        for unit in data()["units"]:
            session.add(
                ModuleUnit(
                    id=units[unit["unit_number"]],
                    module_id=module_id,
                    unit_number=unit["unit_number"],
                    unit_type=unit["unit_type"],
                    order_index=unit["order_index"],
                    title_en=unit["title"]["en"],
                    title_fr=unit["title"]["fr"],
                )
            )
        await session.flush()
        if cached:
            for number in LESSONS:
                content = lesson_content(number, language)
                session.add(_row(module_id, units[number], "lesson", content, language))
            quiz = {"questions": quiz_questions(language)}
            session.add(_row(module_id, units["1.5"], "quiz", quiz, language))
        await session.commit()
    return Seed(course_id, module_id, units)


def _row(module_id, unit_id, content_type, content, language=LANGUAGE) -> GeneratedContent:
    return GeneratedContent(
        id=uuid.uuid4(),
        module_id=module_id,
        module_unit_id=unit_id,
        content_type=content_type,
        language=language,
        level=1,
        country_context="BF",
        content=copy.deepcopy(content),
    )


def service_for(model: FakeModel, **kwargs: Any) -> ModuleStoryService:
    return ModuleStoryService(model, FakeLessonService(), FakeQuizService(), **kwargs)


async def run(
    service: ModuleStoryService,
    sessions: Sessions,
    seed_: Seed,
    *,
    language: str = LANGUAGE,
    **kwargs: Any,
):
    return await service.get_or_generate_module_story(
        seed_.module_id, language, sessions, country="BF", **kwargs
    )


async def fresh(sessions: Sessions, seed_: Seed) -> bool:
    async with sessions.maker() as session:
        record = await find_module_story(session, seed_.module_id, LANGUAGE)
        return record is not None and await module_story_is_fresh(session, record)


async def chapter_rows(sessions: Sessions, seed_: Seed) -> dict[str, StoryCourseRecord]:
    async with sessions.maker() as session:
        rows = (
            await session.execute(
                sa.select(StoryCourseRecord).where(StoryCourseRecord.module_unit_id.is_not(None))
            )
        ).scalars()
        by_id = {v: k for k, v in seed_.units.items()}
        return {by_id[r.module_unit_id]: r for r in rows if r.module_unit_id in by_id}


async def edit_lesson(sessions: Sessions, seed_: Seed, number: str, change) -> None:
    async with sessions.maker() as session:
        row = (
            await session.execute(
                sa.select(GeneratedContent).where(
                    GeneratedContent.module_unit_id == seed_.units[number],
                    GeneratedContent.content_type == "lesson",
                )
            )
        ).scalar_one()
        content = copy.deepcopy(row.content)
        change(content)
        row.content = content
        row.content_revision = (row.content_revision or 1) + 1
        await session.commit()


# --------------------------------------------------------------------------
# A first run
# --------------------------------------------------------------------------


async def test_a_first_run_plans_then_tells_the_chapters_in_order(sessions):
    seed_ = await seed(sessions, cached=False)
    model = FakeModel()
    service = service_for(model)
    record = await run(service, sessions, seed_)
    assert record.is_valid and record.status == "published"
    assert sorted(service.lesson_service.calls) == list(LESSONS)
    assert service.quiz_service.calls == ["1.5"]

    starts = [(k, u) for e, k, u in model.events if e == "start"]
    ends = [(k, u) for e, k, u in model.events if e == "end"]
    index = {item: i for i, item in enumerate(model.events)}
    # Prep: the bible first, before the plan; the plan before any pack or story.
    assert starts[0] == ("bible", "")
    assert index[("end", "plan", "")] < min(
        index[("start", k, u)] for k, u in starts if k in ("pack", "story")
    )
    # The packs start before story 1 ends.
    assert all(
        index[("start", "pack", u)] < index[("end", "story", "1.1")] for u in (*LESSONS, "rally")
    )
    # The stories run strictly one after another, in teaching order; the rally last.
    stories = [u for k, u in starts if k == "story"]
    assert stories == [*LESSONS, "rally"]
    for before, after in zip(stories, stories[1:], strict=False):
        assert index[("end", "story", before)] < index[("start", "story", after)]
    assert ends[-1] == ("story", "rally")
    # One call each: 1 bible + 1 plan + 4 packs + 4 stories.
    assert len(model.calls) == 10
    assert await fresh(sessions, seed_)


async def test_story_two_is_told_after_story_one(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    await run(service_for(model), sessions, seed_)
    message = model.messages[("story", "1.2")][0]
    rows = await chapter_rows(sessions, seed_)
    last_scene = rows["1.1"].content["chapters"][0]["scenes"][-1]["steps"]
    lines = [s[LANGUAGE] for s in last_scene if s["type"] in ("say", "narrate")]
    for line in lines[-6:]:
        assert line in message
    assert data()["stories"]["1.1"]["recap"] in message
    assert "PROPS NOW: basket — empty on the classroom desk" in message
    assert "► 2." in message and "This is the first chapter" not in message
    assert rows["1.1"].source_rows["recap"] == data()["stories"]["1.1"]["recap"]
    assert rows["1.1"].source_rows["pack"]["spine"]["questions"]


async def test_the_rally_sees_every_recap_and_every_card(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    await run(service_for(model), sessions, seed_)
    message = model.messages[("story", "rally")][0]
    for unit in LESSONS:
        assert data()["stories"][unit]["recap"] in message
    rows = await chapter_rows(sessions, seed_)
    for unit in LESSONS:
        for step in rows[unit].content["chapters"][0]["scenes"][0]["steps"]:
            if step["type"] == "concept":
                assert step["title"][LANGUAGE] in message
                assert step[LANGUAGE][0] in message


async def test_a_module_without_a_lesson_has_no_story(sessions):
    seed_ = await seed(sessions)
    async with sessions.maker() as session:
        await session.execute(sa.update(ModuleUnit).values(unit_type="quiz"))
        await session.commit()
    with pytest.raises(NoStoryContent):
        await run(service_for(FakeModel()), sessions, seed_)


# --------------------------------------------------------------------------
# A chapter that fails
# --------------------------------------------------------------------------


async def test_a_failed_chapter_does_not_stop_the_next_one(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    model.unreadable.add(("story", "1.2"))
    with pytest.raises(ChapterGenerationFailed) as failed:
        await run(service_for(model), sessions, seed_)
    assert failed.value.failed_units == ["1.2"]
    assert model.count("story", "1.2") == 2  # the first call and one repair
    assert "The previous chapter is not written yet" in model.messages[("story", "1.3")][0]
    assert model.count("story", "rally") == 0
    async with sessions.maker() as session:
        assert await find_module_story(session, seed_.module_id, LANGUAGE) is None
    rows = await chapter_rows(sessions, seed_)
    assert rows["1.1"].is_valid and rows["1.3"].is_valid
    # A draft that keeps its practice pack: the next run pays only for the story.
    assert rows["1.2"].status == "draft" and rows["1.2"].source_rows["failures"] == 1
    assert rows["1.2"].source_rows["pack"]["spine"]

    # The next run tells only 1.2, from both its neighbours' real scenes. No
    # pack is paid again: 1.2's is in its draft, the rally's was kept with the
    # plan the moment it was made.
    model.unreadable.clear()
    model.calls.clear()
    model.messages.clear()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    assert model.calls == [("story", "1.2"), ("story", "rally")]
    message = model.messages[("story", "1.2")][0]
    assert "=== WHERE THE LAST CHAPTER STOPPED" in message
    assert "=== WHERE THE NEXT CHAPTER STARTS" in message
    first_of_next = data()["stories"]["1.3"]["scenes"][0]["steps"][0][LANGUAGE]
    assert first_of_next in message


async def test_a_chapter_that_cannot_be_made_valid_twice_is_kept_as_a_draft(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    broken = story_answer("1.2")
    broken["scenes"] = []  # no scene at all: never publishable, whatever is settled

    async def answer_broken(system, user, content_type, max_retries=1):
        kind, unit = FakeModel.kind_of(user)
        if (kind, unit) == ("story", "1.2"):
            model.calls.append((kind, unit))
            return {**copy.deepcopy(broken), "props": [], "__complete": True}
        return await FakeModel.generate_structured_content(model, system, user, content_type)

    model.generate_structured_content = answer_broken  # type: ignore[method-assign]
    # The first failure: the module is not written, the next run tries again.
    with pytest.raises(ChapterGenerationFailed):
        await run(service_for(model), sessions, seed_)
    # The second failure with the same inputs reaches the cap: the chapter is
    # kept as a draft and the module is written with its placeholder.
    record = await run(service_for(model), sessions, seed_)
    rows = await chapter_rows(sessions, seed_)
    assert rows["1.2"].status == "draft" and rows["1.2"].source_rows["failures"] == 2
    before = model.count("story", "1.2")
    assert await fresh(sessions, seed_)
    again = await run(service_for(model), sessions, seed_)
    assert model.count("story", "1.2") == before and again.id == record.id
    chapter = next(c for c in record.content["chapters"] if c["covers"]["unit_number"] == "1.2")
    assert chapter["covers"]["status"] == "unavailable"
    assert chapter["scenes"][0]["steps"][0]["fr"].startswith("Cette partie de l'aventure")


# --------------------------------------------------------------------------
# A quiz unit that holds a case study (#2163): one rule for its quiz row
# --------------------------------------------------------------------------


async def add_case_row(sessions: Sessions, seed_: Seed, number: str = "1.5") -> None:
    """A ``case`` row on a unit typed "quiz": it becomes a case checkpoint."""
    async with sessions.maker() as session:
        session.add(_row(seed_.module_id, seed_.units[number], "case", {"scenario": "Un cas."}))
        await session.commit()


async def test_a_quiz_unit_holding_a_case_study_keeps_its_chapters_fresh(sessions):
    """Its quiz row covers the chapters (as freshness reads it): no paid re-tell loop."""
    seed_ = await seed(sessions)
    await add_case_row(sessions, seed_)
    model = FakeModel()
    service = service_for(model)
    record = await run(service, sessions, seed_)
    assert record.is_valid
    assert service.quiz_service.calls == []  # a case checkpoint never gets a quiz made
    assert model.count("story", "rally") == 0  # and no rally: no quiz checkpoint
    rows = await chapter_rows(sessions, seed_)
    assert all(rows[u].source_quiz_content_id is not None for u in LESSONS)
    # The chapters were told with the course's questions of that quiz row.
    assert "[q1]" in model.messages[("plan", "")][0]
    assert await fresh(sessions, seed_)
    model.calls.clear()
    again = await run(service_for(model), sessions, seed_)
    assert model.calls == [] and again.id == record.id
    assert await fresh(sessions, seed_)


async def test_a_quiz_unit_holding_a_case_study_stops_paying_after_the_failure_cap(sessions):
    """The same module whose chapters never validate: kept as drafts after the cap."""
    seed_ = await seed(sessions)
    await add_case_row(sessions, seed_)
    model = FakeModel()
    broken = {**story_answer("1.1"), "scenes": [], "props": [], "__complete": True}

    async def never_valid(system, user, content_type, max_retries=1):
        kind, unit = FakeModel.kind_of(user)
        if kind == "story":
            model.calls.append((kind, unit))
            return copy.deepcopy(broken)
        return await FakeModel.generate_structured_content(model, system, user, content_type)

    model.generate_structured_content = never_valid  # type: ignore[method-assign]
    for _ in range(CHAPTER_FAILURE_CAP - 1):
        with pytest.raises(ChapterGenerationFailed):
            await run(service_for(model), sessions, seed_)
    await run(service_for(model), sessions, seed_)  # the cap: written with placeholders
    rows = await chapter_rows(sessions, seed_)
    assert all(rows[u].source_rows["failures"] == CHAPTER_FAILURE_CAP for u in LESSONS)
    assert await fresh(sessions, seed_)
    model.calls.clear()
    await run(service_for(model), sessions, seed_)
    assert model.calls == []


# --------------------------------------------------------------------------
# A plan made in code: retried once, then kept
# --------------------------------------------------------------------------


async def set_plan_model(sessions: Sessions, seed_: Seed, model: str) -> None:
    async with sessions.maker() as session:
        await session.execute(
            sa.update(StoryModulePlan)
            .where(StoryModulePlan.module_id == seed_.module_id)
            .values(model=model)
        )
        await session.commit()


async def plan_row(sessions: Sessions, seed_: Seed) -> StoryModulePlan:
    async with sessions.maker() as session:
        return (
            await session.execute(
                sa.select(StoryModulePlan).where(StoryModulePlan.module_id == seed_.module_id)
            )
        ).scalar_one()


async def test_a_plan_made_in_code_is_retried_on_the_next_open_once(sessions):
    seed_, model = await told(sessions)
    await set_plan_model(sessions, seed_, DEFAULTED)
    assert not await fresh(sessions, seed_)  # its one retry is due
    record = await run(service_for(model), sessions, seed_)
    # The retry made the same plan: no chapter, pack or rally is paid again.
    assert model.calls == [("plan", "")] and record.is_valid
    assert (await plan_row(sessions, seed_)).model == "fake-model"
    assert await fresh(sessions, seed_)
    model.calls.clear()
    await run(service_for(model), sessions, seed_)
    assert model.calls == []


async def test_a_plan_kept_after_its_retry_is_current(sessions):
    seed_, model = await told(sessions)
    await set_plan_model(sessions, seed_, DEFAULTED_KEPT)
    assert await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    assert model.calls == []


async def test_a_failed_incremental_re_plan_re_tells_only_the_changed_chapter(sessions):
    seed_, model = await told(sessions)
    before = await plan_row(sessions, seed_)

    def change(content):
        content["concepts"][0] += " Même un microbe."

    await edit_lesson(sessions, seed_, "1.2", change)
    model.unreadable.add(("plan", ""))
    await run(service_for(model), sessions, seed_)
    # Two unusable plan answers; only 1.2 is made in code and told again.
    assert model.count("plan") == 2
    assert sorted(c for c in model.calls if c[0] != "plan") == [("pack", "1.2"), ("story", "1.2")]
    after = await plan_row(sessions, seed_)
    assert after.global_digest == before.global_digest
    assert after.model == DEFAULTED and after.content["retry_units"] == ["1.2"]
    assert (
        after.content["beats"][str(seed_.units["1.1"])]
        == before.content["beats"][str(seed_.units["1.1"])]
    )
    # The next open retries that chapter's entry once; nothing else is paid.
    assert not await fresh(sessions, seed_)
    model.unreadable.clear()
    model.calls.clear()
    model.messages.clear()
    await run(service_for(model), sessions, seed_)
    assert "Rewrite ONLY the entry of chapter 1.2" in model.messages[("plan", "")][0]
    assert sorted(model.calls) == [("pack", "1.2"), ("plan", ""), ("story", "1.2")]
    assert (await plan_row(sessions, seed_)).model == "fake-model"
    assert await fresh(sessions, seed_)


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------


async def unmatch_manifest(sessions: Sessions, seed_: Seed) -> None:
    """Make the module row stale without losing its manifest (and its cached rally)."""
    async with sessions.maker() as session:
        record = await find_module_story(session, seed_.module_id, LANGUAGE)
        manifest = copy.deepcopy(record.source_rows)
        manifest["units"][0]["chapter_updated_at"] = "2000-01-01T00:00:00+00:00"
        record.source_rows = manifest
        await session.commit()


async def told(sessions: Sessions) -> tuple[Seed, FakeModel]:
    seed_ = await seed(sessions)
    model = FakeModel()
    await run(service_for(model), sessions, seed_)
    model.calls.clear()
    model.messages.clear()
    return seed_, model


async def test_a_re_merge_with_nothing_changed_makes_no_call(sessions):
    seed_, model = await told(sessions)
    await unmatch_manifest(sessions, seed_)
    assert not await fresh(sessions, seed_)
    record = await run(service_for(model), sessions, seed_)
    assert model.calls == [] and record.is_valid and await fresh(sessions, seed_)


async def test_re_telling_one_chapter_keeps_the_next_one_fresh(sessions):
    seed_, model = await told(sessions)
    async with sessions.maker() as session:
        await session.execute(
            sa.delete(StoryCourseRecord).where(
                StoryCourseRecord.module_unit_id == seed_.units["1.1"]
            )
        )
        await session.commit()
    assert not await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    # Its story (its pack was kept with the plan); 1.2, 1.3 and the rally
    # (same recaps) are kept.
    assert model.calls == [("story", "1.1")]
    assert await fresh(sessions, seed_)


async def test_a_lesson_rewritten_in_prose_changes_nothing(sessions):
    seed_, model = await told(sessions)

    def reword(content):
        content["introduction"] = "Une toute nouvelle introduction, mieux écrite."

    await edit_lesson(sessions, seed_, "1.2", reword)
    assert await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    assert model.calls == []


async def test_a_changed_fact_sheet_re_plans_and_re_tells_only_its_chapter(sessions):
    seed_, model = await told(sessions)

    def change(content):
        content["concepts"][0] += " Même un microbe."

    await edit_lesson(sessions, seed_, "1.2", change)
    assert not await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    assert sorted(model.calls) == [("pack", "1.2"), ("plan", ""), ("story", "1.2")]
    assert "Rewrite ONLY the entry of chapter 1.2" in model.messages[("plan", "")][0]
    assert await fresh(sessions, seed_)


async def test_a_changed_quiz_re_plans_and_re_tells_every_chapter(sessions):
    seed_, model = await told(sessions)
    async with sessions.maker() as session:
        row = (
            await session.execute(
                sa.select(GeneratedContent).where(GeneratedContent.content_type == "quiz")
            )
        ).scalar_one()
        content = copy.deepcopy(row.content)
        content["questions"][0]["explanation"] = "Une nouvelle explication."
        row.content = content
        row.content_revision = 2
        await session.commit()
    assert not await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    assert model.count("plan") == 1 and "Rewrite ONLY" not in model.messages[("plan", "")][0]
    assert sorted(u for k, u in model.calls if k == "story") == sorted([*LESSONS, "rally"])
    # q1's pack is made again (its explanation is in the pack); the others too.
    assert model.count("pack", "1.1") == 1


async def test_a_changed_bible_makes_everything_stale(sessions):
    seed_, model = await told(sessions)
    async with sessions.maker() as session:
        row = await find_bible(session, seed_.course_id)
        content = copy.deepcopy(row.content)
        content["facts"] = content["facts"][:1]
        row.content = content
        row.digest = "0" * 64
        await session.commit()
    assert not await fresh(sessions, seed_)
    await run(service_for(model), sessions, seed_)
    assert model.count("plan") == 1
    assert sorted(u for k, u in model.calls if k == "story") == sorted([*LESSONS, "rally"])


# --------------------------------------------------------------------------
# The time budget
# --------------------------------------------------------------------------


async def test_the_run_stops_before_a_story_call_it_has_no_time_for(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    clock = SimpleNamespace(now=0.0)

    async def tick(system, user, content_type, max_retries=1):
        kind, unit = FakeModel.kind_of(user)
        if (kind, unit) == ("story", "1.1"):
            clock.now = 800.0  # story 1.1 ends with 200 s left: not enough for 1.2
        return await FakeModel.generate_structured_content(model, system, user, content_type)

    model_call = tick
    service = service_for(model)
    service.chapters.claude_service = SimpleNamespace(generate_structured_content=model_call)
    with pytest.raises(StoryDeadlineReached) as stopped:
        await run(service, sessions, seed_, deadline=1000.0, clock=lambda: clock.now)
    assert stopped.value.told == ["1.1"]
    assert model.count("story", "1.2") == 0
    assert set(await chapter_rows(sessions, seed_)) == {"1.1"}
    assert model.count("pack") == 4  # every pack once, each kept as it was made
    # The continuation tells only the rest, and pays for no pack again.
    model.calls.clear()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    assert model.calls == [("story", "1.2"), ("story", "1.3"), ("story", "rally")]


async def test_a_soft_time_limit_inside_a_story_cancels_the_packs_and_propagates(sessions):
    seed_ = await seed(sessions)
    model = FakeModel(delay=0.05)
    model.broken[("story", "1.1")] = SoftTimeLimitExceeded()
    with pytest.raises(SoftTimeLimitExceeded):
        await run(service_for(model), sessions, seed_)
    starts = {(k, u) for e, k, u in model.events if e == "start"}
    ends = {(k, u) for e, k, u in model.events if e == "end"}
    assert starts >= {("story", "1.1")} and ("story", "1.2") not in starts
    assert all(item in ends for item in starts)  # nothing left running


# --------------------------------------------------------------------------
# The #2678 regressions
# --------------------------------------------------------------------------


async def test_a_draft_the_assembler_failed_is_merged_once_more_then_answers_409(sessions):
    """A failed assembly no longer loops: one free re-merge, then it is current (409)."""
    from app.api.v1.schemas.story_course import ValidationIssue, ValidationReport

    seed_, model = await told(sessions)
    failing = ValidationReport(
        ok=False,
        errors=[ValidationIssue(severity="error", code="boom", path="", message="m")],
    )
    await unmatch_manifest(sessions, seed_)
    with patch(
        "app.domain.services.story_module_service.validate_module_story", return_value=failing
    ):
        first = await run(service_for(model), sessions, seed_)
        assert first.source_rows["assembly_failed"] == 1 and not first.is_valid
        assert not await fresh(sessions, seed_)  # merged once more on the next open
        second = await service_for(model).get_or_generate_module_story(
            seed_.module_id, LANGUAGE, sessions, level=2, country="GH"
        )
        assert second.source_rows["assembly_failed"] == ASSEMBLY_FAILURE_CAP
        # Now current: the API answers 409 and starts nothing.
        assert await fresh(sessions, seed_)
    # Not one model call, whatever the level or country of the caller: the
    # plan pins the quiz rows, so the rally's inputs never move.
    assert model.calls == []


async def test_another_level_or_country_never_re_tells_the_rally(sessions):
    seed_, model = await told(sessions)
    async with sessions.maker() as session:
        # A second quiz row for another level and country.
        session.add(
            GeneratedContent(
                id=uuid.uuid4(),
                module_id=seed_.module_id,
                module_unit_id=seed_.units["1.5"],
                content_type="quiz",
                language=LANGUAGE,
                level=2,
                country_context="GH",
                content={"questions": list(reversed(quiz_questions(LANGUAGE)))},
            )
        )
        await session.commit()
    for level, country in ((2, "GH"), (1, "BF"), (2, "GH")):
        await unmatch_manifest(sessions, seed_)
        await service_for(model).get_or_generate_module_story(
            seed_.module_id, LANGUAGE, sessions, level=level, country=country
        )
    assert model.calls == []


async def test_an_outage_of_the_bible_stores_nothing_and_the_next_run_makes_it(sessions):
    seed_ = await seed(sessions)
    model = FakeModel()
    model.broken[("bible", "")] = RuntimeError("401 invalid x-api-key")
    with pytest.raises(StoryProviderUnavailable):
        await run(service_for(model), sessions, seed_)
    async with sessions.maker() as session:
        assert await find_bible(session, seed_.course_id) is None
        count = await session.execute(sa.select(sa.func.count()).select_from(StoryModulePlan))
        assert count.scalar_one() == 0
    model.broken.clear()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    async with sessions.maker() as session:
        bible = await find_bible(session, seed_.course_id)
        assert bible.model == "fake-model"
        assert any(m.get("name") == "Kaboré" for m in bible.content["cast"])


async def test_the_bible_is_never_changed_by_a_story(sessions):
    seed_, model = await told(sessions)
    async with sessions.maker() as session:
        before = (await find_bible(session, seed_.course_id)).digest
    await run(service_for(model), sessions, seed_, force_regenerate=True)
    async with sessions.maker() as session:
        assert (await find_bible(session, seed_.course_id)).digest == before
    assert model.count("bible") == 0


async def test_the_manifest_records_the_plan_and_the_versions(sessions):
    seed_, _model = await told(sessions)
    async with sessions.maker() as session:
        record = await find_module_story(session, seed_.module_id, LANGUAGE)
        plan = (
            await session.execute(
                sa.select(StoryModulePlan).where(StoryModulePlan.module_id == seed_.module_id)
            )
        ).scalar_one()
    manifest = record.source_rows
    assert manifest["assembler"] == MODULE_ASSEMBLER_VERSION == 3
    assert manifest["generator"] == repair.CHAPTER_BUILDER_VERSION == 4
    assert manifest["plan"] == plan.digest
    assert record.content["title"] == plan_answer()["episode_title"]
    assert manifest["rally"]["status"] == "ready" and manifest["rally"]["quiz_rows"]


# --------------------------------------------------------------------------
# Figures (#2681): a dead figure is never offered
# --------------------------------------------------------------------------


async def test_live_figures_drop_a_gone_row_and_a_missing_binary(sessions):
    from app.domain.models.source_image import SourceImage

    alive, dead = uuid.uuid4(), uuid.uuid4()
    async with sessions.maker() as session:
        for image_id, key in ((alive, "figures/alive.webp"), (dead, "figures/dead.webp")):
            session.add(
                SourceImage(
                    id=image_id,
                    source="book",
                    figure_number="Figure 1",
                    image_type="photo",
                    page_number=1,
                    storage_key=key,
                    image_hash="abcd" * 4,
                    figure_kind="micrograph",
                    width=640,
                    height=480,
                )
            )
        await session.commit()

    class Storage:
        def __init__(self) -> None:
            self.heads: list[str] = []

        async def object_exists(self, key: str) -> bool:
            self.heads.append(key)
            return key.endswith("alive.webp")

    storage = Storage()
    refs = [
        {"id": str(dead), "caption_en": "Dead"},
        {"id": str(uuid.uuid4()), "caption_en": "Gone"},
        {"id": str(alive), "caption_en": "Alive", "caption_fr": "Vivante"},
    ]
    async with sessions.maker() as session:
        figures = await live_figures(session, refs, storage)
    assert [f["caption_en"] for f in figures] == ["Alive"]
    assert figures[0]["image_hash"] == "abcd" * 4 and figures[0]["figure_kind"] == "micrograph"
    assert storage.heads.count("figures/dead.webp") == 2  # retried once
