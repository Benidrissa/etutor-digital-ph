"""The episode plan of a module story (#2680): checks, fixes, digests and caching.

Pure tests on the kids biology episode of ``fixtures/story_screenplay_module``
and its plan answer, then :class:`StoryPlanService` on a real PostgreSQL
database with a fake model (skipped without a server).
"""

from __future__ import annotations

import copy
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.prompts.story_from_lesson import build_fact_sheet
from app.ai.prompts.story_plan import build_plan_user_message
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.story_module_plan import StoryModulePlan
from app.domain.services import story_repair as repair
from app.domain.services.story_plan import (
    DEFAULTED,
    DEFAULTED_KEPT,
    PlanCallImpossible,
    PlanCandidate,
    StoryPlanService,
    default_plan,
    entry_refs,
    find_plan_digests,
    global_digest,
    normalise_plan,
    plan_inputs,
    save_pack,
    sha,
    stored_packs,
    validate_plan,
)
from tests._story_db import create_tables, scratch_database, story_tables
from tests.test_story_screenplay_module import make_run, plan_answer


def request(language: str = "en"):
    _service, run, _ctx = make_run(language)
    return run.request


def answer() -> dict[str, Any]:
    return copy.deepcopy(plan_answer())


def plan_codes(raw: dict[str, Any], req=None) -> set[str]:
    return {i.code for i in validate_plan(raw, req or request())}


# --------------------------------------------------------------------------
# validate_plan: each code, positive and negative
# --------------------------------------------------------------------------


def test_the_fixture_plan_passes_every_check():
    assert validate_plan(answer(), request()) == []


@pytest.mark.parametrize(
    ("code", "change"),
    [
        ("plan_chapter_count", lambda p: p["chapters"].pop()),
        ("plan_chapter_count", lambda p: p["chapters"].reverse()),
        ("plan_chapter_count", lambda p: p.pop("rally")),
        ("plan_concept_not_covered", lambda p: p["chapters"][1]["beats"][2].update(ideas=[])),
        ("plan_concept_twice", lambda p: p["chapters"][0]["beats"][1].update(ideas=[1, 2])),
        ("plan_unknown_place", lambda p: p["chapters"][0]["beats"][0].update(place="mars")),
        ("plan_unknown_cast", lambda p: p["chapters"][0]["beats"][0].update(cast=["hero", "x"])),
        (
            "plan_cast_size",
            lambda p: p["chapters"][0]["beats"][0].update(cast=["friend", "mentor"]),
        ),
        ("plan_cast_size", lambda p: p["chapters"][0]["beats"][0].update(cast=["hero"])),
        ("plan_ref_unknown", lambda p: p["chapters"][0]["beats"][2].update(questions=["q99"])),
        ("plan_ref_twice", lambda p: p["chapters"][1]["beats"][2].update(questions=["q1"])),
        (
            "plan_too_many_questions",
            lambda p: p["chapters"][0]["beats"][0].update(questions=["q1", "q2", "q10"]),
        ),
        ("plan_game_count", lambda p: p["chapters"][1].update(game=None)),
        ("plan_game_count", lambda p: p["chapters"][0].update(game="another game")),
        (
            "plan_title_syllabus",
            lambda p: p["chapters"][0].update(
                title={"en": "The signs of life", "fr": "Les signes du vivant"}
            ),
        ),
        (
            "plan_title_syllabus",
            lambda p: p["chapters"][0].update(title={"en": "Lesson 1", "fr": "Leçon 1"}),
        ),
        ("plan_title_syllabus", lambda p: p.update(episode_title={"en": "x" * 41, "fr": "y"})),
        (
            "plan_missing_translation",
            lambda p: p["chapters"][0]["beats"][0].update(discovery={"en": "only English"}),
        ),
        (
            "plan_too_long",
            lambda p: p["chapters"][0]["beats"][0].update(card_title={"en": "a" * 41, "fr": "b"}),
        ),
        ("plan_too_long", lambda p: p["catchphrases"][0].update(en="c" * 51)),
        ("plan_hook_missing", lambda p: p["chapters"][2].update(ends_on="")),
        ("plan_premise_is_syllabus", lambda p: p.update(want="Learn about living things")),
        ("plan_premise_is_syllabus", lambda p: p.update(logline="Discover the mystery of cells")),
    ],
)
def test_validate_plan_flags(code, change):
    raw = answer()
    change(raw)
    assert code in plan_codes(raw)


def test_a_question_of_another_lessons_quiz_is_flagged():
    req = request()
    req.candidates = [replace(c, covers=("1.2",)) if c.ref == "q1" else c for c in req.candidates]
    assert "plan_ref_wrong_lesson" in plan_codes(answer(), req)


# --------------------------------------------------------------------------
# normalise_plan: what the code fixes after the one repair
# --------------------------------------------------------------------------


def test_a_missing_idea_is_appended_to_the_last_beat_and_recorded():
    raw = answer()
    raw["chapters"][1]["beats"][2]["ideas"] = []
    plan, gaps = normalise_plan(raw, request())
    beats = plan["chapters"][1]["beats"]
    assert sorted(i for b in beats for i in b["ideas"]) == [1, 2, 3]
    assert 3 in beats[-1]["ideas"] and any("IDEA 3 added" in g for g in gaps)


def test_refs_are_known_used_once_and_kept_by_their_own_lesson():
    req = request()
    req.candidates = [replace(c, covers=("1.3",)) if c.ref == "q2" else c for c in req.candidates]
    raw = answer()
    raw["chapters"][0]["beats"][2]["questions"] = ["q99", "q4"]  # unknown; 1.2's
    plan, gaps = normalise_plan(raw, req)
    refs = {c["unit"]: entry_refs(c) for c in plan["chapters"]}
    assert refs["1.1"] == ["q1", "q3", "q4"]  # q2 is not 1.1's, q99 is nothing
    assert "q4" not in refs["1.2"]  # never in two lesson chapters
    assert any("q99" in g for g in gaps) and any("q2 is not this lesson's" in g for g in gaps)


def test_the_rally_is_filled_to_three_questions_unused_first():
    raw = answer()
    raw["rally"]["steps"] = [{"from_unit": "1.1", "uses": "x", "questions": []}]
    plan, gaps = normalise_plan(raw, request())
    assert entry_refs(plan["rally"], rally=True) == ["q10", "q11", "q12"]
    assert "rally: filled up to its questions" in gaps


def test_exactly_one_game_is_kept_and_one_is_given_if_none():
    raw = answer()
    raw["chapters"][0]["game"] = "first game"
    plan, _ = normalise_plan(raw, request())
    games = [c["game"] for c in plan["chapters"]] + [plan["rally"]["game"]]
    assert [g for g in games if g] == ["first game"]
    raw["chapters"][0]["game"] = raw["chapters"][1]["game"] = None
    plan, gaps = normalise_plan(raw, request())
    assert sum(bool(c["game"]) for c in plan["chapters"]) == 1 and any("game" in g for g in gaps)


def test_a_bad_place_and_cast_are_fixed_and_a_syllabus_title_replaced():
    raw = answer()
    raw["chapters"][0]["beats"][0].update(place="mars", cast=["friend", "ghost"])
    raw["chapters"][0]["title"] = {"en": "The signs of life", "fr": "Les signes du vivant"}
    plan, gaps = normalise_plan(raw, request())
    beat = plan["chapters"][0]["beats"][0]
    assert beat["place"] == "rood_woko_market" and beat["cast"][0] == "hero"
    assert 2 <= len(beat["cast"]) <= 3 and "ghost" not in beat["cast"]
    assert plan["chapters"][0]["title"] == {"en": "The shy leaf", "fr": "La feuille timide"}
    assert "1.1: syllabus title replaced" in gaps


def test_a_plan_made_in_code():
    req = request()
    plan = default_plan(req)
    assert [len(c["beats"]) for c in plan["chapters"]] == [3, 3, 3]
    assert plan["chapters"][0]["title"]["en"] == "The signs of life"
    assert plan["logline"] and plan["chapters"][0]["ends_on"] == ""
    per_chapter = [len(entry_refs(c)) for c in plan["chapters"]]
    assert all(n <= 4 for n in per_chapter) and sum(per_chapter) == 12
    assert len(entry_refs(plan["rally"], rally=True)) >= 3
    assert sum(bool(c["game"]) for c in plan["chapters"]) == 1


# --------------------------------------------------------------------------
# Digests: what the plan depends on
# --------------------------------------------------------------------------


def test_a_prose_change_keeps_the_inputs_a_fact_sheet_change_moves_one_lesson():
    req = request()
    before = plan_inputs(req)
    lesson = req.lessons[1]
    content = {"introduction": "A new introduction.", "concepts": list(lesson.sheet.ideas)}
    content["key_points"] = list(lesson.sheet.key_facts)
    req.lessons[1] = replace(lesson, sheet=build_fact_sheet(content))
    assert plan_inputs(req) == before  # prose only: nothing moves
    content["concepts"][0] += " Even a germ."
    req.lessons[1] = replace(lesson, sheet=build_fact_sheet(content))
    after = plan_inputs(req)
    assert after["global"] == before["global"]
    changed = [k for k in before["lessons"] if before["lessons"][k] != after["lessons"][k]]
    assert changed == [str(lesson.unit_id)]


@pytest.mark.parametrize("what", ["quiz", "bible", "roster", "version"])
def test_a_quiz_bible_roster_or_version_change_moves_the_global_inputs(what, monkeypatch):
    req = request()
    before = plan_inputs(req)["global"]
    if what == "quiz":
        req.quiz_rows = [[*row[:2], row[2] + 1, row[3]] for row in req.quiz_rows]
    elif what == "bible":
        content = copy.deepcopy(req.bible.content)
        content["facts"] = []
        req.bible = type(req.bible).of(content)
    elif what == "roster":
        req.roster_digest = "another"
    else:
        monkeypatch.setattr(repair, "PLAN_VERSION", repair.PLAN_VERSION + 1)
    assert plan_inputs(req)["global"] != before


def test_an_incremental_re_plan_rewrites_one_chapter_and_moves_no_other_digest():
    req = request()
    plan, _ = normalise_plan(answer(), req)
    rewritten = answer()
    rewritten["chapters"][1]["goal"] = "A brand new goal."
    rewritten["chapters"][1]["title"] = {"en": "A new title", "fr": "Un nouveau titre"}
    rewritten["chapters"][1]["ends_on"] = "Something else."
    rewritten["chapters"][0]["goal"] = "Changed behind our back."
    rewritten["logline"] = "Changed too."
    new, _gaps = normalise_plan(rewritten, req, previous=plan, rewritten={"1.2"})
    assert new["chapters"][0] == plan["chapters"][0]
    assert new["chapters"][2] == plan["chapters"][2]
    assert global_digest(new) == global_digest(plan)
    middle = new["chapters"][1]
    assert middle["goal"] == "A brand new goal."
    for key in ("title", "when", "opens_on", "ends_on", "game", "paper_task"):
        assert middle[key] == plan["chapters"][1][key], key
    from app.domain.services.story_plan import beat_digest

    def digest(p, unit):
        entry = next(c for c in p["chapters"] if c["unit"] == unit)
        return beat_digest(entry, [req.candidate(r).key for r in entry_refs(entry)])

    assert digest(new, "1.1") == digest(plan, "1.1") and digest(new, "1.3") == digest(plan, "1.3")
    assert digest(new, "1.2") != digest(plan, "1.2")


def test_the_plan_message_states_the_contract():
    message = build_plan_user_message(request("fr"))
    assert "REQUEST: plan the episode" in message and "then the rally" in message
    assert "LESSON 1.2" in message and "IDEA 3:" in message
    assert '"rally"' in message and "The rally takes 3 to 6." in message
    assert "[q1] (quiz 1.5, covers lessons 1.1–1.3)" in message
    assert "Aminata" in message.split("Never use these names")[1].split("\n")[0]


# --------------------------------------------------------------------------
# The service on PostgreSQL
# --------------------------------------------------------------------------


class FakeModel:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.messages: list[str] = []
        self._model = "fake-plan-model"

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.messages.append(user)
        value = self.answers[min(len(self.messages), len(self.answers)) - 1]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with scratch_database("story_plan") as url:
        create_tables(url, story_tables())
        yield url


@pytest.fixture
def maker(database_url):
    """A session maker on the scratch database; its engine is made on the test's own loop."""
    return _LazyMaker(database_url)


class _LazyMaker:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = None

    def __call__(self) -> AsyncSession:
        if self.engine is None:
            self.engine = create_async_engine(self.url, pool_size=4, poolclass=None)
        return async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)()


async def seeded_request(maker):
    req = request()
    course_id, module_id = uuid.uuid4(), uuid.uuid4()
    async with maker() as session:
        session.add(Course(id=course_id, slug=f"c-{course_id.hex[:8]}", title_en="C", title_fr="C"))
        await session.flush()
        session.add(
            Module(
                id=module_id,
                module_number=uuid.uuid4().int % 1_000_000 + 10,
                level=1,
                title_en="M",
                title_fr="M",
                course_id=course_id,
            )
        )
        await session.commit()
    req.module_id = module_id
    return req


async def stored(maker, req) -> StoryModulePlan:
    async with maker() as session:
        return (
            await session.execute(
                sa.select(StoryModulePlan).where(StoryModulePlan.module_id == req.module_id)
            )
        ).scalar_one()


async def test_a_plan_is_made_once_and_reused(maker):
    req = await seeded_request(maker)
    model = FakeModel({**answer(), "__complete": True})
    service = StoryPlanService(model)
    async with maker() as session:
        first = await service.get_or_create(session, req, system_prompt="s")
    async with maker() as session:
        again = await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 1 and first.calls == 1 and again.calls == 0
    assert again.digest == first.digest and again.global_digest == first.global_digest
    row = await stored(maker, req)
    assert row.model == "fake-plan-model" and row.version == repair.PLAN_VERSION
    assert set(row.content) == {"plan", "inputs", "gaps", "pins", "beats", "packs"}
    assert row.content["beats"]["rally"] and len(row.content["beats"]) == 4


async def test_a_plan_with_errors_gets_one_repair_then_code_fixes_the_rest(maker):
    req = await seeded_request(maker)
    bad = answer()
    bad["chapters"][0]["beats"][0]["place"] = "mars"
    model = FakeModel(bad, bad)
    async with maker() as session:
        plan = await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 2
    assert "=== REPAIR (attempt 1 of 1) ===" in model.messages[1]
    assert "[plan_unknown_place]" in model.messages[1]
    assert plan.plan["chapters"][0]["beats"][0]["place"] == "rood_woko_market"


async def test_unreadable_twice_stores_a_plan_made_in_code_retried_once(maker):
    req = await seeded_request(maker)
    model = FakeModel(ValueError("truncated"), {"raw_response": "nope"})
    async with maker() as session:
        plan = await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    assert plan.defaulted and (await stored(maker, req)).model == DEFAULTED
    assert len(model.messages) == 2
    # The next run retries once; still unusable: kept until the inputs change.
    async with maker() as session:
        kept = await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    assert (await stored(maker, req)).model == DEFAULTED_KEPT and len(model.messages) == 4
    async with maker() as session:
        again = await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    assert again.digest == kept.digest and len(model.messages) == 4


async def test_an_outage_stores_no_plan(maker):
    req = await seeded_request(maker)
    model = FakeModel(RuntimeError("529 overloaded"))
    async with maker() as session:
        with pytest.raises(PlanCallImpossible):
            await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    async with maker() as session:
        count = await session.execute(
            sa.select(sa.func.count())
            .select_from(StoryModulePlan)
            .where(StoryModulePlan.module_id == req.module_id)
        )
        assert count.scalar_one() == 0


async def test_a_changed_fact_sheet_re_plans_only_its_chapter(maker):
    req = await seeded_request(maker)
    model = FakeModel({**answer(), "__complete": True})
    service = StoryPlanService(model)
    async with maker() as session:
        first = await service.get_or_create(session, req, system_prompt="s")
    lesson = req.lessons[1]
    ideas = list(lesson.sheet.ideas)
    ideas[0] += " Even a germ."
    req.lessons[1] = replace(
        lesson,
        sheet=build_fact_sheet({"concepts": ideas, "key_points": list(lesson.sheet.key_facts)}),
    )
    async with maker() as session:
        second = await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 2
    assert "Rewrite ONLY the entry of chapter 1.2" in model.messages[1]
    assert second.global_digest == first.global_digest
    assert second.chapter("1.1") == first.chapter("1.1")


async def test_a_changed_quiz_re_plans_everything(maker):
    req = await seeded_request(maker)
    model = FakeModel({**answer(), "__complete": True})
    service = StoryPlanService(model)
    async with maker() as session:
        await service.get_or_create(session, req, system_prompt="s")
    req.quiz_rows = [[*row[:2], row[2] + 1, row[3]] for row in req.quiz_rows]
    async with maker() as session:
        await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 2 and "Rewrite ONLY" not in model.messages[1]


def _with_changed_sheet(req, index: int = 1):
    lesson = req.lessons[index]
    ideas = list(lesson.sheet.ideas)
    ideas[0] += " Even a germ."
    req.lessons[index] = replace(
        lesson,
        sheet=build_fact_sheet({"concepts": ideas, "key_points": list(lesson.sheet.key_facts)}),
    )


async def test_an_incremental_re_plan_that_fails_keeps_every_other_entry(maker):
    """Unusable twice on one lesson's change: only that chapter is made in code."""
    req = await seeded_request(maker)
    good = {**answer(), "__complete": True}
    model = FakeModel(good, ValueError("truncated"), {"raw_response": "nope"}, good)
    service = StoryPlanService(model)
    async with maker() as session:
        first = await service.get_or_create(session, req, system_prompt="s")
    _with_changed_sheet(req)
    async with maker() as session:
        second = await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 3 and "Rewrite ONLY the entry of chapter 1.2" in model.messages[1]
    # The good plan is not thrown away: the global block and the other
    # chapters are kept byte for byte, so nothing else goes stale.
    assert second.global_digest == first.global_digest
    assert second.chapter("1.1") == first.chapter("1.1")
    assert second.chapter("1.3") == first.chapter("1.3")
    assert second.rally == first.rally
    assert second.chapter("1.2") != first.chapter("1.2")
    assert entry_refs(second.chapter("1.2")) == entry_refs(first.chapter("1.2"))
    row = await stored(maker, req)
    assert row.model == DEFAULTED and row.content["retry_units"] == ["1.2"]
    assert "chapters 1.2 made in code" in row.content["gaps"]
    async with maker() as session:
        assert await find_plan_digests(session, req.module_id, req.language) is None
    # The next run retries that chapter once, incrementally.
    async with maker() as session:
        third = await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 4
    assert "Rewrite ONLY the entry of chapter 1.2" in model.messages[3]
    assert third.global_digest == first.global_digest
    assert third.chapter("1.1") == first.chapter("1.1")
    row = await stored(maker, req)
    assert row.model == "fake-plan-model" and "retry_units" not in row.content
    async with maker() as session:
        assert await find_plan_digests(session, req.module_id, req.language) is not None


async def test_an_incremental_retry_that_fails_again_is_kept(maker):
    req = await seeded_request(maker)
    bad = ValueError("truncated")
    model = FakeModel({**answer(), "__complete": True}, bad, bad, bad, bad)
    service = StoryPlanService(model)
    async with maker() as session:
        first = await service.get_or_create(session, req, system_prompt="s")
    _with_changed_sheet(req)
    for _ in range(2):
        async with maker() as session:
            plan = await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 5
    row = await stored(maker, req)
    assert row.model == DEFAULTED_KEPT and "retry_units" not in row.content
    assert plan.chapter("1.1") == first.chapter("1.1")
    async with maker() as session:
        assert await find_plan_digests(session, req.module_id, req.language) is not None
        await service.get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 5  # kept: never asked again for these inputs


async def test_a_plan_made_in_code_is_stale_for_its_one_retry_only(maker):
    req = await seeded_request(maker)
    model = FakeModel(ValueError("truncated"))
    async with maker() as session:
        await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    async with maker() as session:
        assert await find_plan_digests(session, req.module_id, req.language) is None
        await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    async with maker() as session:
        found = await find_plan_digests(session, req.module_id, req.language)
    assert found is not None and (await stored(maker, req)).model == DEFAULTED_KEPT


async def test_a_provider_error_on_the_repair_keeps_the_first_answer(maker):
    req = await seeded_request(maker)
    bad = answer()
    bad["chapters"][0]["beats"][0]["place"] = "mars"
    model = FakeModel(bad, RuntimeError("429 rate limited"))
    async with maker() as session:
        plan = await StoryPlanService(model).get_or_create(session, req, system_prompt="s")
    assert len(model.messages) == 2
    # The paid first answer is kept, fixed in code; it is a real plan.
    assert plan.plan["chapters"][0]["beats"][0]["place"] == "rood_woko_market"
    assert (await stored(maker, req)).model == "fake-plan-model"


async def test_packs_are_kept_one_by_one_and_survive_a_new_plan(maker):
    req = await seeded_request(maker)
    service = StoryPlanService(FakeModel({**answer(), "__complete": True}))
    async with maker() as session:
        await service.get_or_create(session, req, system_prompt="s")

    async def keep(key: str) -> None:
        async with maker() as session:
            await save_pack(
                session, req.module_id, req.language, key, {"inputs": key, "spine": {"k": key}}
            )

    import asyncio

    await asyncio.gather(*(keep(k) for k in ("a", "b", "c", "rally")))
    async with maker() as session:
        packs = await stored_packs(session, req.module_id, req.language)
    assert set(packs) == {"a", "b", "c", "rally"} and packs["b"]["spine"] == {"k": "b"}
    # A re-plan keeps them: their inputs say whether they still fit.
    _with_changed_sheet(req)
    async with maker() as session:
        await service.get_or_create(session, req, system_prompt="s")
    async with maker() as session:
        assert set(await stored_packs(session, req.module_id, req.language)) == set(packs)


def test_margo_is_cast_in_the_beats_where_she_speaks():
    message = build_plan_user_message(request("fr"))
    assert 'Margo speaks only in a beat whose "cast" lists "margo"' in message


def test_a_module_without_a_rally_resolves_on_its_last_chapter():
    req = request("fr")
    assert "no rally" not in build_plan_user_message(req).split("RULES:")[1]
    req.has_rally = False
    message = build_plan_user_message(req)
    assert "This module has no rally: chapter 1.3 is the climax" in message
    assert "never a cliffhanger" in message and '"paid_off": "1.3"' in message
    assert '"paid_off": "rally"' not in message and '"rally": {' not in message
    assert "is past by the last chapter" in message


def test_candidates_keep_their_content_key():
    req = request()
    candidate = req.candidates[0]
    assert isinstance(candidate, PlanCandidate)
    assert candidate.key == sha(
        [candidate.mcq.stem, candidate.mcq.options, candidate.mcq.correct_index]
    )
