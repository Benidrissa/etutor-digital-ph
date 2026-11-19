"""The slot builder in a module run (#2713), on a real PostgreSQL database, fake model.

Same module and harness as ``test_story_module_service.py`` (it needs a server
and creates only the story tables; skipped without one). What is proved here:

* with the default settings the run is the classic one: the same calls, a
  chapter row with no ``variant``, a manifest entry with none;
* turning ``story-builder-variant`` to ``slots`` changes NOTHING already told:
  the module stays fresh and no model is called;
* a chapter told again (forced) under ``slots`` records its variant, in its row
  and in the module's manifest, costs one ``slots`` call, and plays in the same
  module story (validated, assembled) as a classic one;
* a plan without a ``cast_policy`` (legacy) is told classic even under ``slots``;
* the repair budget and the cheaper story model come from their settings;
* the run's counters of calls and tokens by kind are in the manifest.
"""

from __future__ import annotations

import contextlib
import copy
from typing import Any

import pytest

from app.domain.services import story_bible, story_calls
from app.domain.services.story_module_service import find_module_story
from tests._story_db import create_tables, scratch_database, story_tables
from tests.test_story_module_service import (
    LANGUAGE,
    LESSONS,
    FakeModel,
    Sessions,
    assess,  # noqa: F401 — an autouse fixture of the harness
    chapter_rows,
    fresh,
    run,
    seed,
    service_for,
)
from tests.test_story_screenplay_module import story_answer
from tests.test_story_slots import ROW, TEXT

pytestmark = pytest.mark.asyncio(loop_scope="session")

CHAPTERS = {"1": "1.1", "2": "1.2", "3": "1.3"}


@pytest.fixture(autouse=True)
def no_mentor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A NEW plan (it carries a ``cast_policy``): no mentor."""
    monkeypatch.setattr(story_bible, "_mentor_policy", lambda *_a, **_k: "none")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The admin settings the story generator reads; a test sets keys in it."""
    values: dict[str, Any] = {}
    monkeypatch.setattr(story_calls, "_setting", lambda key, default: values.get(key, default))
    return values


@pytest.fixture(scope="module")
def database_url():
    with scratch_database("story_slots") as url:
        create_tables(url, story_tables())
        yield url


@pytest.fixture
async def sessions(database_url):
    import sqlalchemy as sa

    made = Sessions(database_url)
    yield made
    names = ", ".join(t.name for t in story_tables())
    async with made.engine.begin() as conn:
        await conn.execute(sa.text(f"TRUNCATE {names} CASCADE"))
    await made.engine.dispose()


class SlotsModel(FakeModel):
    """The module's fake model, which also answers a chapter's slot call."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.slot_answers: list[dict[str, Any]] = []

    @staticmethod
    def kind_of(user: str) -> tuple[str, str]:
        if user.startswith("REQUEST: fill the"):
            index = user.split("of chapter ", 1)[1].split(" ", 1)[0]
            return "slots", CHAPTERS[index]
        return FakeModel.kind_of(user)

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        kind, unit = self.kind_of(user)
        if kind != "slots":
            return await super().generate_structured_content(system, user, content_type)
        self.calls.append((kind, unit))
        self.messages.setdefault((kind, unit), []).append(user)
        answer: dict[str, Any] = {}
        offset = 100 * int(unit.split(".")[1])  # each chapter says its own lines
        for n, match in enumerate(ROW.finditer(user), start=offset):
            slot_id, role = match.groups()
            en, fr = TEXT[role]
            answer[slot_id] = {"en": f"{en} number {n}", "fr": f"{fr} numéro {n}"}
        self.slot_answers.append(answer)
        return {**answer, "__complete": True}


def manifest_of(record) -> dict[str, Any]:
    return record.source_rows


# --------------------------------------------------------------------------
# The default is the classic run, unchanged
# --------------------------------------------------------------------------


async def test_the_default_settings_run_the_classic_builder_and_record_no_variant(
    sessions, settings
):
    seed_ = await seed(sessions, cached=False)
    model = SlotsModel()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    # 1 bible + 1 plan + 4 packs + 4 stories: exactly the calls of before.
    assert len(model.calls) == 10 and model.count("slots") == 0
    rows = await chapter_rows(sessions, seed_)
    assert all(
        "variant" not in r.source_rows and "slots" not in r.source_rows for r in rows.values()
    )
    assert all("variant" not in e for e in manifest_of(record)["units"])
    # The counters: every call of the run, by kind.
    counted = manifest_of(record)["model_calls"]
    assert {k: v["calls"] for k, v in counted.items()} == {
        "bible": 1,
        "plan": 1,
        "pack": 4,
        "story": 3,
        "rally": 1,
    }
    assert all(v["output_tokens"] > 0 for v in counted.values())


# --------------------------------------------------------------------------
# Flipping the setting never makes a story stale
# --------------------------------------------------------------------------


async def test_flipping_the_variant_leaves_every_stored_chapter_fresh_and_pays_nothing(
    sessions, settings
):
    seed_ = await seed(sessions, cached=False)
    model = SlotsModel()
    record = await run(service_for(model), sessions, seed_)
    before = len(model.calls)
    settings["story-builder-variant"] = "slots"
    assert await fresh(sessions, seed_)
    again = await run(service_for(model), sessions, seed_)
    assert again.id == record.id and len(model.calls) == before
    settings["story-builder-variant"] = "classic"
    assert await fresh(sessions, seed_)


# --------------------------------------------------------------------------
# A chapter told again under slots
# --------------------------------------------------------------------------


async def test_a_forced_run_under_slots_tells_each_lesson_chapter_in_one_slots_call(
    sessions, settings
):
    seed_ = await seed(sessions, cached=False)
    model = SlotsModel()
    await run(service_for(model), sessions, seed_)
    settings["story-builder-variant"] = "slots"
    model.calls.clear()
    model.messages.clear()
    record = await run(service_for(model), sessions, seed_, force_regenerate=True)
    assert record.is_valid, record.validation_report["errors"]
    assert record.status == "published"
    # plan + 4 packs + 3 slots chapters + the rally (classic): the bible is kept.
    assert model.count("slots") == 3 and model.count("story") == 1  # the rally
    assert model.count("story", "rally") == 1 and model.count("plan") == 1
    assert len(model.calls) == 9
    rows = await chapter_rows(sessions, seed_)
    for number in LESSONS:
        row = rows[number]
        assert row.is_valid and row.status == "published"
        assert row.source_rows["variant"] == "slots"
        assert (
            row.source_rows["slots"]["slots"] >= 18 and row.source_rows["slots"]["fallbacks"] == []
        )
        assert row.content["sira_builder"] == 4  # the version is NOT bumped
    manifest = manifest_of(record)
    assert [e.get("variant") for e in manifest["units"] if e["role"] == "lesson"] == ["slots"] * 3
    assert manifest["generator"] == 4
    counted = manifest["model_calls"]
    assert (
        counted["slots"]["calls"] == 3 and "story" not in counted and counted["rally"]["calls"] == 1
    )
    # The module story is the same module story: validated, assembled, fresh.
    assert record.content["chapters"] and await fresh(sessions, seed_)
    # Flipping back keeps it fresh too: a chapter is remade only when told again.
    settings["story-builder-variant"] = "classic"
    assert await fresh(sessions, seed_)


async def test_a_slots_chapter_has_the_codes_scenes_and_the_models_lines(sessions, settings):
    seed_ = await seed(sessions, cached=False)
    settings["story-builder-variant"] = "slots"
    model = SlotsModel()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    rows = await chapter_rows(sessions, seed_)
    steps = [s for c in rows["1.1"].content["chapters"] for sc in c["scenes"] for s in sc["steps"]]
    first = model.slot_answers[0]
    texts = {s.get(LANGUAGE) for s in steps if isinstance(s.get(LANGUAGE), str)}
    assert first["b1.set"][LANGUAGE] in texts and first["b1.hook"][LANGUAGE] in texts
    # The plan's own discovery, in the plan's words: written by nobody at all.
    assert "La feuille se ferme quand on la touche : le vivant réagit !" in texts
    assert any(s["type"] == "ask" and s["ref"] == "q1" for s in steps)


async def test_a_legacy_plan_is_told_classic_even_under_slots(sessions, settings, monkeypatch):
    monkeypatch.setattr(story_bible, "_mentor_policy", lambda *_a, **_k: None)
    seed_ = await seed(sessions, cached=False)
    settings["story-builder-variant"] = "slots"
    model = SlotsModel()
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid and model.count("slots") == 0 and model.count("story") == 4
    rows = await chapter_rows(sessions, seed_)
    assert all("variant" not in r.source_rows for r in rows.values())


async def test_a_chapter_the_slots_cannot_make_valid_is_told_the_classic_way(sessions, settings):
    seed_ = await seed(sessions, cached=False)
    settings["story-builder-variant"] = "slots"
    settings["story-max-repair-calls"] = 0
    model = SlotsModel()

    async def unusable(system, user, content_type, max_retries=1):
        kind, unit = SlotsModel.kind_of(user)
        if kind == "slots" and unit == "1.2":
            model.calls.append((kind, unit))
            return {"__complete": True}  # not one slot
        return await SlotsModel.generate_structured_content(model, system, user, content_type)

    model.generate_structured_content = unusable  # type: ignore[method-assign]
    record = await run(service_for(model), sessions, seed_)
    assert record.is_valid
    assert model.count("slots", "1.2") == 1 and model.count("story", "1.2") == 1
    rows = await chapter_rows(sessions, seed_)
    assert "variant" not in rows["1.2"].source_rows
    assert rows["1.1"].source_rows["variant"] == rows["1.3"].source_rows["variant"] == "slots"
    async with sessions.maker() as session:
        stored = await find_module_story(session, seed_.module_id, LANGUAGE)
        assert stored is not None


# --------------------------------------------------------------------------
# The repair budget and the cheaper model
# --------------------------------------------------------------------------


async def test_the_repair_budget_setting_bounds_a_packs_repairs(sessions, settings):
    seed_ = await seed(sessions, cached=False)
    settings["story-max-repair-calls"] = 0
    model = SlotsModel()
    bad = {"questions": "junk"}

    async def broken_pack(system, user, content_type, max_retries=1):
        kind, unit = SlotsModel.kind_of(user)
        if (kind, unit) == ("pack", "1.1"):
            model.calls.append((kind, unit))
            return {**copy.deepcopy(bad), "__complete": True}
        return await SlotsModel.generate_structured_content(model, system, user, content_type)

    model.generate_structured_content = broken_pack  # type: ignore[method-assign]
    service = service_for(model)
    assert service._repairs() == 0
    with contextlib.suppress(Exception):  # the pack is unusable: only its calls matter
        await run(service, sessions, seed_)
    assert model.count("pack", "1.1") == 1  # no repair: the budget is 0
    settings["story-max-repair-calls"] = 2
    assert service_for(model)._repairs() == 2


async def test_the_story_model_setting_picks_a_distinct_client_for_story_calls_only(
    sessions, settings
):
    seed_ = await seed(sessions, cached=False)
    content, story = SlotsModel(), SlotsModel()
    service = service_for(content, story_service=story)
    assert service.chapters.story_service is story
    record = await run(service, sessions, seed_)
    assert record.is_valid
    # The bible, the plan and the packs stay on the content model; the screenplays
    # and the rally are written by the story model.
    assert {k for k, _u in content.calls} == {"bible", "plan", "pack"}
    assert {k for k, _u in story.calls} == {"story"} and len(story.calls) == 4
    story_answer("1.1")  # the fixture is the story model's answer too
