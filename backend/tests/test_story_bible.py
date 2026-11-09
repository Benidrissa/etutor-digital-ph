"""The course bible: one cast and set of places per course, one model call (#2674)."""

from __future__ import annotations

import asyncio
import copy
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.prompts.story_bible import build_bible_messages
from app.domain.models.course import Course
from app.domain.models.story_bible import StoryCourseBible
from app.domain.services.story_bible import (
    BibleModule,
    StoryBible,
    StoryBibleService,
    StoryBibleUnavailable,
    bible_digest,
    default_bible,
    doc_cast,
    doc_places,
    mission_for,
    mission_of,
    normalise_bible,
)
from tests._story_db import create_tables, scratch_database, story_tables

MODULE = BibleModule(uuid.UUID(int=1), 1, {"en": "What is alive?", "fr": "Qu'est-ce qui vit ?"})
OTHER = BibleModule(uuid.UUID(int=2), 2, {"en": "Cells", "fr": "Les cellules"})


class FakeClaude:
    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str]] = []
        self._model = "fake-model-1"

    async def generate_structured_content(self, system, user, content_type, max_retries=1):
        self.calls.append((system, user))
        await asyncio.sleep(0.01)
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return copy.deepcopy(answer)


def course(**overrides: Any) -> SimpleNamespace:
    values = {
        "id": uuid.UUID(int=99),
        "title_en": "Life detectives",
        "title_fr": "Les détectives du vivant",
        "description_en": "Biology for curious children.",
        "description_fr": "",
        "taxonomy_categories": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("is_kids", "variants"), [(True, ["girl", "boy"]), (False, ["woman", "man"])]
)
def test_an_empty_answer_still_makes_a_complete_bible(is_kids, variants):
    content = normalise_bible({}, is_kids=is_kids, modules=[MODULE])
    cast = {m["id"]: m for m in content["cast"]}
    assert list(cast) == ["hero", "friend", "mentor", "family", "margo"]
    assert [m["role"] for m in content["cast"]] == ["hero", "friend", "mentor", "family", "tutor"]
    assert [v["id"] for v in cast["hero"]["variants"]] == variants
    assert cast["hero"]["name"] == "{child}" and cast["friend"]["name"] == "{friend}"
    assert cast["friend"]["default_name"]
    assert cast["margo"]["kind"] == "ai_tutor" and "margouillat" in cast["margo"]["look"]
    kind = "child" if is_kids else "adult"
    assert cast["hero"]["kind"] == cast["friend"]["kind"] == kind
    assert cast["mentor"]["kind"] == "adult"
    assert len(content["places"]) == 5
    assert all(p["look"] and set(p["title"]) == {"en", "fr"} for p in content["places"])
    assert content["missions"][str(MODULE.module_id)]["en"]
    assert content["audience"] == ("kids" if is_kids else "adult")


def test_names_read_the_same_in_both_languages():
    answer = {
        "cast": [
            {"id": "mentor", "name": "Mr Kaboré"},
            {"id": "family", "name": "Mme Ouédraogo"},
            {"id": "friend", "name": "{friend}", "default_name": "M. Awa"},
            {"id": "hero", "name": "Nandi"},  # the hero is always the learner
        ]
    }
    cast = {m["id"]: m for m in normalise_bible(answer, is_kids=True)["cast"]}
    assert cast["mentor"]["name"] == "Kaboré"
    assert cast["family"]["name"] == "Ouédraogo"
    assert cast["friend"]["default_name"] == "Awa"
    assert cast["hero"]["name"] == "{child}"


def test_a_cast_without_a_family_member_keeps_it_out():
    answer = {"cast": [{"id": "hero"}, {"id": "friend"}, {"id": "mentor"}, {"id": "margo"}]}
    ids = [m["id"] for m in normalise_bible(answer, is_kids=False)["cast"]]
    assert ids == ["hero", "friend", "mentor", "margo"]


def test_roles_are_read_from_aliases_and_voices_are_clamped():
    answer = {
        "cast": [
            {"role": "teacher", "name": "Sanou", "voice": {"pitch": 9, "rate": 0.1}},
            {"id": "peer", "default_name": "Ali", "look": "a boy in a red cap."},
        ]
    }
    cast = {m["id"]: m for m in normalise_bible(answer, is_kids=True)["cast"]}
    assert cast["mentor"]["name"] == "Sanou"
    assert cast["mentor"]["voice"] == {"pitch": 2.0, "rate": 0.7}
    assert cast["friend"]["default_name"] == "Ali"
    assert cast["friend"]["look"] == "a boy in a red cap"


def test_places_are_slugged_deduplicated_capped_and_padded():
    place = {"title": {"en": "Big market", "fr": "Grand marché"}, "look": "stalls"}
    many = [{**place, "id": f"Place {n}"} for n in range(12)]
    content = normalise_bible({"places": many}, is_kids=True)
    assert [p["id"] for p in content["places"]] == [f"place_{n}" for n in range(8)]
    few = normalise_bible(
        {"places": [{**place, "id": "market"}, {**place, "id": "market"}, {"id": "x"}]},
        is_kids=True,
    )
    ids = [p["id"] for p in few["places"]]
    assert ids[0] == "market" and len(ids) == 5 and len(set(ids)) == 5


def test_facts_without_a_source_are_marked_invented():
    content = normalise_bible(
        {
            "places": [{"id": "market", "title": {"en": "M", "fr": "M"}, "look": "stalls"}],
            "facts": [
                {"en": "A", "fr": "A", "source": "Wikipedia", "place": "market"},
                {"en": "B", "fr": "B"},
                {"en": "C", "fr": "C", "source": "Somewhere", "invented": True},
                {"en": "", "fr": ""},
            ],
        },
        is_kids=True,
    )
    assert content["facts"] == [
        {"en": "A", "fr": "A", "source": "Wikipedia", "invented": False, "place": "market"},
        {"en": "B", "fr": "B", "invented": True},
        {"en": "C", "fr": "C", "invented": True},
    ]


def test_missions_are_keyed_by_module_and_default_when_missing():
    content = normalise_bible(
        {"missions": [{"module": "1", "en": "Find the treasure", "fr": "Trouver le trésor"}]},
        is_kids=True,
        modules=[MODULE, OTHER],
    )
    assert mission_of(content, MODULE.module_id) == {
        "en": "Find the treasure",
        "fr": "Trouver le trésor",
    }
    fallback = mission_of(content, str(OTHER.module_id))
    assert "Cells" in fallback["en"] and "Les cellules" in fallback["fr"]
    assert mission_of(content, uuid.uuid4()) is None


@pytest.mark.parametrize("raw", [None, [], "bible", 7, {"cast": "x", "places": {"a": 1}}])
def test_any_answer_shape_normalises(raw):
    content = normalise_bible(raw, is_kids=False)
    assert len(content["cast"]) == 5 and len(content["places"]) == 5


def test_the_digest_and_the_story_view():
    bible = default_bible(True, [MODULE])
    assert bible.digest == bible_digest(bible.content) == StoryBible.of(bible.content).digest
    assert default_bible(True, [MODULE]).digest == bible.digest  # deterministic
    assert default_bible(False, [MODULE]).digest != bible.digest
    cast = doc_cast(bible.content)
    assert all("about" not in member for member in cast)
    assert set(cast[0]) == {"id", "name", "kind", "art", "voice", "role", "look", "variants"}
    assert doc_places(bible.content) == [
        {"id": p["id"], "title": p["title"], "look": p["look"]} for p in bible.content["places"]
    ]


def test_the_prompt_asks_for_the_contract():
    system, user = build_bible_messages(course(), [MODULE, OTHER], is_kids=True, country="BF")
    assert "margouillat" in system and "{child}" in system and "{friend}" in system
    assert "BF (West Africa)" in system
    assert '"id": "girl"' in user and '"id": "boy"' in user
    assert "- Module 1: What is alive? / Qu'est-ce qui vit ?" in user
    assert "- Module 2: Cells / Les cellules" in user
    _system, adult = build_bible_messages(course(), [MODULE], is_kids=False, country="")
    assert '"id": "woman"' in adult and "colleague" in _system


# --------------------------------------------------------------------------
# One model call per course
# --------------------------------------------------------------------------


class FakeResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    """Holds bible rows by course; no lock (not PostgreSQL)."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, StoryCourseBible] = {}
        self.pending: list[StoryCourseBible] = []
        self.commits = 0

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    async def execute(self, statement):
        course_id = next(iter(statement.compile().params.values()))
        return FakeResult(self.rows.get(course_id))

    def add(self, row):
        self.pending.append(row)

    async def commit(self):
        for row in self.pending:
            self.rows[row.course_id] = row
        self.pending.clear()
        self.commits += 1


async def test_the_first_story_of_a_course_writes_its_bible_and_the_rest_reuse_it():
    answer = {
        "places": [{"id": "rood_woko", "title": {"en": "Market", "fr": "Marché"}, "look": "stalls"}]
    }
    model = FakeClaude(answer)
    service = StoryBibleService(model)
    session = FakeSession()

    first = await service.get_or_create(session, course(), [MODULE], country="BF")
    again = await service.get_or_create(session, course(), [MODULE, OTHER], country="CI")

    assert len(model.calls) == 1  # one model call for the course, ever
    assert session.commits == 1
    row = session.rows[course().id]
    assert row.digest == first.digest == again.digest
    assert row.model == "fake-model-1"
    assert again.content == first.content
    assert first.content["places"][0]["id"] == "rood_woko" and first.content["country"] == "BF"
    # Another course gets its own.
    other = await service.get_or_create(session, course(id=uuid.UUID(int=100)), [MODULE])
    assert len(model.calls) == 2 and other.digest != first.digest


async def test_an_unreadable_answer_is_asked_again_once_then_fails():
    model = FakeClaude({"raw_response": True}, ValueError("truncated"))
    session = FakeSession()
    with pytest.raises(StoryBibleUnavailable):
        await StoryBibleService(model).get_or_create(session, course(), [MODULE])
    assert len(model.calls) == 2 and session.rows == {}

    model = FakeClaude({"raw_response": True}, {"cast": [{"id": "mentor", "name": "Zida"}]})
    bible = await StoryBibleService(model).get_or_create(session, course(), [MODULE])
    assert len(model.calls) == 2
    assert next(m for m in bible.content["cast"] if m["id"] == "mentor")["name"] == "Zida"


# --------------------------------------------------------------------------
# On PostgreSQL: two stories of one course started together make one bible
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    with scratch_database("story_bible") as url:
        create_tables(url, story_tables())
        yield url


async def test_concurrent_stories_of_a_course_make_one_bible_with_one_call(database_url):
    engine = create_async_engine(database_url, pool_size=4)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    course_id = uuid.uuid4()
    try:
        async with maker() as session:
            session.add(
                Course(id=course_id, slug=f"c-{course_id.hex[:8]}", title_en="C", title_fr="C")
            )
            await session.commit()
            the_course = await session.get(Course, course_id)
        model = FakeClaude({"cast": [{"id": "mentor", "name": "Zida"}]})
        service = StoryBibleService(model)

        async def make() -> StoryBible:
            async with maker() as session:
                return await service.get_or_create(session, the_course, [MODULE])

        first, second = await asyncio.gather(make(), make())

        assert len(model.calls) == 1
        assert first.digest == second.digest
        async with maker() as session:
            count = await session.execute(sa.select(sa.func.count()).select_from(StoryCourseBible))
            assert count.scalar_one() == 1
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# Review of #2678
# --------------------------------------------------------------------------


def test_missions_and_facts_are_never_cut_mid_sentence():
    mission = {
        "en": "Find out which treasures in Grandma's basket are alive before Friday's"
        " science fair at the school",
        "fr": "Découvrir quels trésors du panier de Mamie sont vivants avant la foire"
        " scientifique de vendredi à l'école",
    }
    fact = {
        "en": "Rood Woko, the central market of Ouagadougou, burned in 2003 and was"
        " rebuilt; it reopened in 2009 with hundreds of stalls under its roofs.",
        "fr": "Rood Woko, le marché central de Ouagadougou, a brûlé en 2003 puis a été"
        " reconstruit ; il a rouvert en 2009 avec des centaines d'étals.",
        "source": "Wikipedia",
    }
    title = {"en": "A very long place title " * 6, "fr": "Un très long titre de lieu " * 6}
    content = normalise_bible(
        {
            "missions": [{"module": 1, **mission}],
            "facts": [fact],
            "places": [{"id": "market", "title": title, "look": "stalls"}],
        },
        is_kids=True,
        modules=[MODULE],
    )
    assert mission_of(content, MODULE.module_id) == mission
    assert content["facts"][0]["en"] == fact["en"] and content["facts"][0]["fr"] == fact["fr"]
    assert len(content["places"][0]["title"]["en"]) <= 80


def test_a_module_without_a_stored_mission_gets_one_from_its_title():
    content = normalise_bible({}, is_kids=True, modules=[MODULE])
    assert mission_for(content, MODULE.module_id, 1, MODULE.title) == mission_of(
        content, MODULE.module_id
    )
    later = mission_for(content, str(OTHER.module_id), 2, {"en": "Cells", "fr": ""})
    assert "Cells" in later["en"] and "Cells" in later["fr"]
    assert mission_for(content, OTHER.module_id, 2, OTHER.title) == mission_for(
        content, OTHER.module_id, 2, OTHER.title
    )  # deterministic
    assert str(OTHER.module_id) not in content["missions"]  # the bible is left alone


@pytest.mark.parametrize(
    ("answer", "usable"),
    [
        ({"cast": [{"id": "mentor"}]}, True),
        ({"places": [{"id": "x", "title": {"en": "X", "fr": "X"}, "look": "l"}]}, True),
        ({"bible": {"cast": [{"role": "teacher", "name": "Zida"}]}}, True),
        ({"story_bible": {"places": []}, "__complete": True}, False),
        ({"cast": [{"id": "dragon"}], "places": [{"id": "x"}]}, False),
        ({"text": "Here is your bible"}, False),
        ({}, False),
        ("bible", False),
    ],
)
def test_an_answer_with_no_cast_and_no_place_is_not_usable(answer, usable):
    from app.domain.services.story_bible import usable_answer

    assert (usable_answer(answer) is not None) is usable


async def test_a_wrapped_answer_is_opened():
    model = FakeClaude({"bible": {"cast": [{"id": "mentor", "name": "Zida"}]}, "__complete": True})
    bible = await StoryBibleService(model).get_or_create(FakeSession(), course(), [MODULE])
    assert next(m for m in bible.content["cast"] if m["id"] == "mentor")["name"] == "Zida"


async def test_a_junk_answer_is_asked_again_then_fails_and_stores_nothing():
    model = FakeClaude({"text": "Sorry"}, {"cast": [{"id": "dragon"}]})
    session = FakeSession()
    with pytest.raises(StoryBibleUnavailable):
        await StoryBibleService(model).get_or_create(session, course(), [MODULE])
    assert len(model.calls) == 2 and session.rows == {}


async def test_defaults_are_stored_only_when_the_model_cannot_be_called():
    from app.domain.services.story_bible import DEFAULTED, DEFAULTED_KEPT

    down = FakeClaude(RuntimeError("provider down"))
    session = FakeSession()
    service = StoryBibleService(down)
    first = await service.get_or_create(session, course(), [MODULE])
    row = session.rows[course().id]
    assert row.model == DEFAULTED and len(down.calls) == 2
    assert first.content["cast"] == normalise_bible({}, is_kids=False, modules=[MODULE])["cast"]

    # The next story tries once more: it works, and replaces the defaults.
    service.claude_service = FakeClaude({"cast": [{"id": "mentor", "name": "Zida"}]})
    second = await service.get_or_create(session, course(), [MODULE])
    assert row.model == "fake-model-1" and row.digest == second.digest != first.digest
    assert len(service.claude_service.calls) == 1

    # Or it fails again: the defaults are kept for good, and never retried.
    session = FakeSession()
    service = StoryBibleService(FakeClaude(RuntimeError("down")))
    kept = await service.get_or_create(session, course(), [MODULE])
    again = await service.get_or_create(session, course(), [MODULE])
    assert session.rows[course().id].model == DEFAULTED_KEPT
    assert again.digest == kept.digest
    assert len(service.claude_service.calls) == 4
    third = await service.get_or_create(session, course(), [MODULE])
    assert third.digest == kept.digest and len(service.claude_service.calls) == 4
