"""Shared stock art for story mode (#2714): slots, adoption, serving, promotion.

No image call is ever made: the generator gets fakes that record what it was
asked to draw. The tests that need PostgreSQL make a scratch database like the
other story tests (skipped when no server is reachable).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.domain.models.story_art import (
    CHARACTER_POSES,
    EXTRA_CHARACTER_POSES,
    POSES,
    StoryArt,
)
from app.domain.models.story_stock_art import StoryStockArt
from app.domain.services import story_art_service as svc
from app.domain.services import story_stock_art as stock
from app.domain.services.story_art_service import (
    ART_VERSION,
    ArtItem,
    build_art_map,
    collect_looks,
    plan_art,
)
from app.tasks.story_art import story_art_stock_settings

NOW = datetime(2026, 11, 19, tzinfo=UTC)
COURSE = uuid.UUID("5c0a8b7e-1d2f-4e3a-9b8c-7d6e5f4a3b2c")
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "promote_story_stock.py"
_spec = importlib.util.spec_from_file_location("promote_story_stock", _SCRIPT)
script = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = script
_spec.loader.exec_module(script)


def _row(item: ArtItem, pose: str, *, stock_id=None, status="ready", digest=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        kind=item.kind,
        key=item.key,
        pose=pose,
        look_digest=digest or item.digest,
        status=status,
        art_version=ART_VERSION,
        model="stock" if stock_id else "gpt-image",
        error=None,
        failed_runs=0,
        retry_after=None,
        stock_id=stock_id,
        width=100,
        height=100,
    )


def _images(poses):
    return {pose: stock.StockImage(uuid.uuid4(), pose) for pose in poses}


class TestPlaceTheme:
    @pytest.mark.parametrize(
        ("place", "look", "theme"),
        [
            ("school_classroom", "", "classroom"),
            ("market", "", "market"),
            ("family_home", "", "home"),
            ("health_centre", "", "clinic"),
            ("river_bank", "", "village"),
            ("farm_field", "", "farm"),
            ("school_courtyard", "", "yard"),
            ("home", "", "home"),  # the older catalogue wins
            ("school_yard", "", "yard"),
            ("the_square", "a clinic waiting room", "clinic"),  # the look, when the id says nothing
            ("meeting_hall", "", "office"),
        ],
    )
    def test_follows_the_players_rule(self, place, look, theme):
        assert stock.place_theme(place, look) == theme

    def test_no_theme_when_the_player_would_only_guess(self):
        assert stock.place_theme("zzz_plaza", "a grey space") is None


class TestSlots:
    def test_a_hero_variant_then_the_role(self):
        assert stock.slot_candidates("character", "hero:girl", "hero", "girl") == [
            ("character", "hero", "girl"),
            ("character", "hero", ""),
        ]

    def test_another_role_is_keyed_by_audience(self):
        assert stock.slot_candidates("character", "mentor", "mentor", "kids") == [
            ("character", "mentor", "kids"),
            ("character", "mentor", ""),
        ]

    def test_a_place_by_its_id_then_its_theme(self):
        assert stock.slot_candidates("place", "river_bank", look="") == [
            ("place", "village", "river_bank"),
            ("place", "village", ""),
        ]

    def test_no_role_or_no_theme_means_no_slot(self):
        assert stock.slot_candidates("character", "x", "", "") == []
        assert stock.slot_candidates("place", "zzz_plaza", look="") == []

    def test_a_character_needs_all_four_base_poses(self):
        index = {("character", "mentor", "kids"): _images(CHARACTER_POSES[:3])}
        assert stock.find_stock(index, "character", "mentor", "mentor", "kids") is None
        index[("character", "mentor", "kids")] = _images(CHARACTER_POSES)
        assert stock.find_stock(index, "character", "mentor", "mentor", "kids") is not None

    def test_the_specific_slot_beats_the_generic_one(self):
        specific = _images(CHARACTER_POSES)
        index = {
            ("character", "mentor", "kids"): specific,
            ("character", "mentor", ""): _images(CHARACTER_POSES),
        }
        assert stock.find_stock(index, "character", "mentor", "mentor", "kids") is specific
        # An audience with no stock of its own falls back to the generic image.
        assert (
            stock.find_stock(index, "character", "mentor", "mentor", "adult")
            is index[("character", "mentor", "")]
        )

    def test_extras_are_adopted_only_when_the_stock_has_them(self):
        images = _images([*CHARACTER_POSES, "sad"])
        assert stock.stock_poses("character", images) == [*CHARACTER_POSES, "sad"]
        assert stock.stock_poses("place", _images(["backdrop"])) == ["backdrop"]


class TestItemsCarryTheirSlot:
    def test_roles_and_variants_of_a_bible(self):
        doc = {
            "audience": "kids",
            "cast": [
                {
                    "id": "hero",
                    "role": "hero",
                    "variants": [{"id": "girl", "look": "g"}, {"id": "boy", "look": "b"}],
                },
                {"id": "mentor", "role": "mentor", "look": "m"},
                {"id": "margo", "role": "tutor", "look": "t"},
            ],
            "places": [{"id": "market", "look": "p"}],
        }
        found = {(i.key): (i.role, i.variant) for i in collect_looks([doc])}
        assert found == {
            "hero:girl": ("hero", "girl"),
            "hero:boy": ("hero", "boy"),
            "mentor": ("mentor", "kids"),
            "margo": ("tutor", "kids"),
            "market": ("", ""),
        }

    def test_role_and_variant_are_not_part_of_an_items_identity(self):
        assert ArtItem("character", "mentor", "look", "mentor", "kids") == ArtItem(
            "character", "mentor", "look"
        )


class TestArtMap:
    def test_a_stock_row_is_served_at_the_stock_url_and_poses_beyond_the_four_are_not_counted(self):
        item = ArtItem("character", "mentor", "look", "mentor")
        shared = _images([*CHARACTER_POSES, *EXTRA_CHARACTER_POSES])
        rows = [_row(item, pose, stock_id=shared[pose].id) for pose in shared]
        art = build_art_map([item], rows, now=NOW)
        assert art.art["status"] == "ready" and art.outstanding == 0
        assert art.art["characters"]["mentor"] == {
            pose: f"/api/v1/story-art/{shared[pose].id}/data" for pose in shared
        }

    def test_a_course_with_its_own_art_is_served_as_before(self):
        item = ArtItem("character", "mentor", "look", "mentor")
        rows = [_row(item, pose) for pose in CHARACTER_POSES]
        poses = build_art_map([item], rows, now=NOW).art["characters"]["mentor"]
        assert poses == {
            pose: f"/api/v1/story-art/{r.id}/data"
            for pose, r in zip(CHARACTER_POSES, rows, strict=True)
        }

    def test_stock_rows_are_ready_so_a_run_plans_nothing_for_them(self):
        item = ArtItem("character", "mentor", "look", "mentor")
        rows = [_row(item, pose, stock_id=uuid.uuid4()) for pose in CHARACTER_POSES]
        assert plan_art([item], rows, now=NOW) == []

    def test_the_art_version_is_not_bumped(self):
        # Existing courses keep their art: a bump would redraw every one (#2714).
        assert ART_VERSION == 2


class TestModel:
    def test_stock_poses_are_the_story_art_poses(self):
        assert set(StoryStockArt.__table__.c.pose.type.__class__.__mro__)  # column exists
        assert {"surprised", "sad"} <= set(POSES)

    def test_one_live_image_per_slot_index(self):
        (index,) = [
            i for i in StoryStockArt.__table__.indexes if i.name == "uq_story_stock_art_slot"
        ]
        assert index.unique
        assert [c.name for c in index.columns] == ["kind", "theme", "variant", "pack", "pose"]
        assert "retired" in str(index.dialect_options["postgresql"]["where"])

    def test_a_course_row_may_point_at_stock(self):
        column = StoryArt.__table__.c.stock_id
        assert column.nullable
        (fk,) = column.foreign_keys
        assert fk.target_fullname == "story_stock_art.id" and fk.ondelete == "RESTRICT"


class TestSettings:
    def test_defaults_keep_todays_behaviour(self):
        assert story_art_stock_settings(lambda key, default: default) == {
            "use_stock": True,
            "stock_pack": "west_africa",
            "custom_cap": 0,
        }

    def test_values(self):
        values = {
            "story-art-use-stock": False,
            "story-art-stock-pack": "sahel",
            "story-art-max-custom-images": "6",
        }
        got = story_art_stock_settings(lambda key, default: values.get(key, default))
        assert got == {"use_stock": False, "stock_pack": "sahel", "custom_cap": 6}

    def test_nonsense_is_zero(self):
        assert story_art_stock_settings(lambda key, default: "many")["custom_cap"] == 0

    def test_the_settings_are_registered(self):
        from app.infrastructure.config.platform_defaults import SETTING_DEFINITIONS

        keys = {d.key for d in SETTING_DEFINITIONS}
        assert {
            "story-art-use-stock",
            "story-art-stock-pack",
            "story-art-max-custom-images",
        } <= keys


class TestPromotionPlan:
    def _course(self):
        girl = ArtItem("character", "hero:girl", "g", "hero", "girl")
        mentor = ArtItem("character", "mentor", "m", "mentor", "kids")
        odd = ArtItem("character", "odd", "o")
        market = ArtItem("place", "market", "p")
        rows = [
            *(_row(girl, pose) for pose in CHARACTER_POSES),
            *(_row(mentor, pose) for pose in CHARACTER_POSES[:3]),  # think missing
            _row(market, "backdrop"),
        ]
        return [girl, mentor, odd, market], rows

    def test_promotes_complete_items_only_and_says_why_not(self):
        items, rows = self._course()
        promotions, notes = script.plan_promotion(items, rows, set(), generic=False)
        assert {(p.kind, p.theme, p.variant, p.pose) for p in promotions} == {
            *(("character", "hero", "girl", pose) for pose in CHARACTER_POSES),
            ("place", "market", "market", "backdrop"),
        }
        assert any("mentor" in n and "think" in n for n in notes)
        assert any("odd" in n and "no stock slot" in n for n in notes)

    def test_generic_places_are_stored_for_their_theme(self):
        items, rows = self._course()
        promotions, _ = script.plan_promotion(items, rows, set(), generic=True)
        (place,) = [p for p in promotions if p.kind == "place"]
        assert (place.theme, place.variant) == ("market", "")

    def test_a_slot_that_already_has_stock_is_left_alone(self):
        items, rows = self._course()
        taken = {("character", "hero", "girl", pose) for pose in CHARACTER_POSES}
        promotions, notes = script.plan_promotion(items, rows, taken, generic=False)
        assert all(p.kind == "place" for p in promotions)
        assert any("already has stock" in n for n in notes)

    def test_a_course_that_adopted_stock_is_not_a_source(self):
        girl = ArtItem("character", "hero:girl", "g", "hero", "girl")
        rows = [_row(girl, pose, stock_id=uuid.uuid4()) for pose in CHARACTER_POSES]
        promotions, notes = script.plan_promotion([girl], rows, set(), generic=False)
        assert promotions == [] and notes

    def test_a_stale_look_is_not_promoted(self):
        girl = ArtItem("character", "hero:girl", "g", "hero", "girl")
        rows = [_row(girl, pose, digest="0" * 64) for pose in CHARACTER_POSES]
        assert script.plan_promotion([girl], rows, set(), generic=False)[0] == []

    def test_the_script_is_a_dry_run_unless_told_otherwise(self):
        args = script.parse_args(["promote", "--course", "x"])
        assert args.apply is False
        assert script.parse_args(["approve", "--all-candidates"]).apply is False


# -- the data route ---------------------------------------------------------------


class _Session:
    def __init__(self, art=None, stock=None):
        self.art, self.stock = art, stock

    async def execute(self, statement):
        sql = str(statement)
        row = self.stock if "story_stock_art" in sql else self.art
        return SimpleNamespace(first=lambda: row)


class TestDataRoute:
    async def _get(self, session):
        from app.api.v1.story_art import get_story_art_data

        return await get_story_art_data(uuid.uuid4(), session)

    async def test_an_approved_stock_image_is_served_immutable(self):
        response = await self._get(_Session(stock=("approved", b"WEBP")))
        assert response.body == b"WEBP"
        assert "immutable" in response.headers["cache-control"]

    async def test_a_retired_image_still_serves_the_courses_that_use_it(self):
        assert (await self._get(_Session(stock=("retired", b"WEBP")))).body == b"WEBP"

    async def test_a_candidate_is_never_served(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as caught:
            await self._get(_Session(stock=("candidate", b"WEBP")))
        assert caught.value.status_code == 404

    async def test_a_course_image_is_still_served_first(self):
        assert (await self._get(_Session(art=("ready", b"OWN")))).body == b"OWN"


# -- the migration ----------------------------------------------------------------

_MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "versions" / "114_story_stock_art.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("migration_114", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMigration114:
    def test_revision_chain(self):
        module = _migration()
        assert module.revision == "114_story_stock_art" and len(module.revision) <= 32
        assert module.down_revision == "113_story_asset_catalogues"

    def test_the_pose_check_lists_the_model_poses(self):
        module = _migration()
        for pose in POSES:
            assert f"'{pose}'" in module._POSES


# -- PostgreSQL ---------------------------------------------------------------------


def _png(size=(40, 60), colour=(200, 50, 50, 255)) -> bytes:
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGBA", size, colour).save(buffer, format="WEBP")
    return buffer.getvalue()


class _Fakes:
    """Image fakes that record every call (there must be none when stock covers it)."""

    def __init__(self):
        self.calls = []

    async def generate(self, prompt, **kwargs):
        self.calls.append(("generate", prompt))
        from tests.test_story_art import backdrop_png, figure_png

        size = kwargs.get("size")
        return (backdrop_png() if size == svc.BACKDROP_SIZE else figure_png()), "gpt-image"

    async def edit(self, prompt, image, **kwargs):
        self.calls.append(("edit", prompt))
        from tests.test_story_art import figure_png

        return figure_png(), "gpt-image"


DOC = {
    "audience": "kids",
    "cast": [
        {"id": "mentor", "role": "mentor", "look": "mentor look"},
        {"id": "margo", "role": "tutor", "look": "margo look"},
    ],
    "places": [{"id": "school_classroom", "look": "a classroom"}],
    "facts": [],
}


def _db_scenario(scenario):
    """Run ``scenario(maker)`` on a scratch database holding the story tables."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.models import Base
    from tests._story_db import create_tables, scratch_database, story_tables

    with scratch_database("story_stock") as url:
        create_tables(url, [*story_tables(), Base.metadata.tables["story_art"]])

        async def run():
            engine = create_async_engine(url)
            maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                await scenario(maker)
            finally:
                await engine.dispose()

        asyncio.run(run())


async def _course(maker, doc=DOC) -> uuid.UUID:
    from app.domain.models.course import Course
    from app.domain.models.story_bible import StoryCourseBible

    course_id = uuid.uuid4()
    async with maker() as session:
        session.add(Course(id=course_id, slug=f"c-{course_id.hex[:8]}", title_en="C", title_fr="C"))
        await session.flush()
        session.add(
            StoryCourseBible(
                id=uuid.uuid4(), course_id=course_id, content=doc, digest="0" * 64, model="claude"
            )
        )
        await session.commit()
    return course_id


async def _add_stock(maker, kind, theme, variant, poses, status="approved", pack="west_africa"):
    ids = {}
    async with maker() as session:
        for pose in poses:
            data = _png()
            row = StoryStockArt(
                id=uuid.uuid4(),
                kind=kind,
                theme=theme,
                variant=variant,
                pack=pack,
                pose=pose,
                status=status,
                image_data=data,
                width=40,
                height=60,
                content_sha256="0" * 64,
            )
            session.add(row)
            ids[pose] = row.id
        await session.commit()
    return ids


def test_on_postgres_a_run_adopts_approved_stock_and_draws_nothing_for_it():
    async def scenario(maker):
        course_id = await _course(maker)
        mentor = await _add_stock(maker, "character", "mentor", "kids", CHARACTER_POSES)
        classroom = await _add_stock(maker, "place", "classroom", "", ["backdrop"])
        fakes = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit
        ).run(course_id)
        # The tutor has no stock: drawn as before (4 images). The rest is adopted.
        assert report["adopted"] == 5 and report["ready"] == 4
        assert sum(1 for kind, _ in fakes.calls if kind == "generate") == 1
        assert not any("mentor look" in p or "classroom" in p for _k, p in fakes.calls)

        async with maker() as session:
            rows = await svc.load_art_rows(session, course_id)
            looks = await svc.load_course_looks(session, course_id)
        adopted = {(r.key, r.pose): r.stock_id for r in rows if r.stock_id}
        assert adopted == {
            **{("mentor", pose): mentor[pose] for pose in CHARACTER_POSES},
            ("school_classroom", "backdrop"): classroom["backdrop"],
        }
        art = build_art_map(looks.items, rows, accepted=looks.accepted).art
        assert art["status"] == "ready"
        assert (
            art["places"]["school_classroom"] == f"/api/v1/story-art/{classroom['backdrop']}/data"
        )
        assert art["characters"]["mentor"]["idle"] == f"/api/v1/story-art/{mentor['idle']}/data"
        # A second run has nothing to do: stock rows are ready.
        again = _Fakes()
        second = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=again.generate, edit=again.edit
        ).run(course_id)
        assert second["planned"] == 0 and again.calls == []

    _db_scenario(scenario)


def test_on_postgres_a_candidate_or_another_pack_is_never_adopted():
    async def scenario(maker):
        course_id = await _course(maker)
        await _add_stock(maker, "character", "mentor", "kids", CHARACTER_POSES, status="candidate")
        await _add_stock(maker, "place", "classroom", "", ["backdrop"], pack="other_pack")
        fakes = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit
        ).run(course_id)
        assert "adopted" not in report and report["ready"] == 9  # drawn as before

    _db_scenario(scenario)


def test_on_postgres_stock_can_be_switched_off():
    async def scenario(maker):
        course_id = await _course(maker)
        await _add_stock(maker, "place", "classroom", "", ["backdrop"])
        fakes = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit, use_stock=False
        ).run(course_id)
        assert "adopted" not in report and report["ready"] == 9

    _db_scenario(scenario)


def test_on_postgres_existing_art_is_never_replaced_by_stock():
    async def scenario(maker):
        course_id = await _course(maker)
        fakes = _Fakes()
        first = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit
        ).run(course_id)
        assert first["ready"] == 9
        async with maker() as session:
            before = {(r.key, r.pose): r.id for r in await svc.load_art_rows(session, course_id)}
        # Stock appears afterwards: the course keeps its own images (same ids).
        await _add_stock(maker, "character", "mentor", "kids", CHARACTER_POSES)
        again = _Fakes()
        second = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=again.generate, edit=again.edit
        ).run(course_id)
        assert second["planned"] == 0 and again.calls == []
        async with maker() as session:
            after = {(r.key, r.pose): r.id for r in await svc.load_art_rows(session, course_id)}
        assert after == before

    _db_scenario(scenario)


def test_on_postgres_the_custom_cap_leaves_the_rest_to_an_operator():
    async def scenario(maker):
        course_id = await _course(maker)
        fakes = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit, custom_cap=5
        ).run(course_id)
        # Mentor (4) fits; margo (4) would make 8 > 5; the classroom (1) fits.
        assert report["ready"] == 5 and report["capped"] == ["margo"]
        async with maker() as session:
            rows = {(r.key, r.pose): r for r in await svc.load_art_rows(session, course_id)}
            looks = await svc.load_course_looks(session, course_id)
        assert rows[("margo", "idle")].status == "failed"
        assert rows[("margo", "idle")].error == svc.CUSTOM_CAP_ERROR
        assert rows[("margo", "idle")].retry_after is None  # final: no view says "being drawn"
        art = build_art_map(looks.items, list(rows.values()), accepted=looks.accepted)
        assert art.outstanding == 0 and art.art["status"] == "partial"
        # An operator's run (retry_failed) ignores the cap and draws it.
        later = _Fakes()
        done = await svc.StoryArtGenerator(
            maker,
            model="gpt-image",
            generate=later.generate,
            edit=later.edit,
            custom_cap=5,
            retry_failed=True,
        ).run(course_id)
        assert done["ready"] == 4

    _db_scenario(scenario)


def test_on_postgres_one_live_image_per_slot_and_retired_ones_are_history():
    async def scenario(maker):
        await _add_stock(maker, "place", "market", "", ["backdrop"])
        with pytest.raises(sa.exc.IntegrityError):
            await _add_stock(maker, "place", "market", "", ["backdrop"], status="candidate")
        async with maker() as session:
            await session.execute(sa.text("UPDATE story_stock_art SET status = 'retired'"))
            await session.commit()
        await _add_stock(maker, "place", "market", "", ["backdrop"])  # a new id, a new URL

    _db_scenario(scenario)


def test_on_postgres_the_script_promotes_then_approves():
    async def scenario(maker):
        course_id = await _course(maker)
        fakes = _Fakes()
        await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=fakes.generate, edit=fakes.edit
        ).run(course_id)
        slug = None
        async with maker() as session:
            from app.domain.models.course import Course

            slug = (await session.execute(sa.select(Course.slug))).scalar_one()

        args = ["promote", "--course", slug]
        assert await script.main(args, session_factory=maker) == 0  # dry run
        async with maker() as session:
            assert (
                await session.execute(sa.text("SELECT count(*) FROM story_stock_art"))
            ).scalar_one() == 0
        assert await script.main([*args, "--apply"], session_factory=maker) == 0
        assert await script.main([*args, "--apply"], session_factory=maker) == 0  # idempotent
        async with maker() as session:
            rows = (
                await session.execute(sa.select(StoryStockArt.status, StoryStockArt.theme))
            ).all()
        assert len(rows) == 9 and {s for s, _t in rows} == {"candidate"}
        assert {t for _s, t in rows} == {"mentor", "tutor", "classroom"}

        # Candidates are not adopted: another course still draws.
        other = await _course(maker)
        more = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=more.generate, edit=more.edit
        ).run(other)
        assert "adopted" not in report

        # Nothing is approved without --apply, then everything is, once.
        assert await script.main(["approve", "--all-candidates"], session_factory=maker) == 0
        async with maker() as session:
            assert (
                await session.execute(
                    sa.select(sa.func.count()).where(StoryStockArt.status == "approved")
                )
            ).scalar_one() == 0
        assert (
            await script.main(["approve", "--all-candidates", "--apply"], session_factory=maker)
            == 0
        )
        third = await _course(maker)
        last = _Fakes()
        report = await svc.StoryArtGenerator(
            maker, model="gpt-image", generate=last.generate, edit=last.edit
        ).run(third)
        assert report["adopted"] == 9 and last.calls == []  # zero image calls for a new course

    _db_scenario(scenario)


def test_on_postgres_migration_114_upgrades_downgrades_and_matches_the_model(monkeypatch):
    """109 -> 114 keeps an existing course's row, widens the pose check, and comes back down."""
    from alembic import command
    from alembic.config import Config

    from app.domain.models import Base
    from app.infrastructure.config.settings import settings
    from tests._story_db import create_tables, scratch_database, story_tables, sync_engine

    versions = _MIGRATION.parent
    with scratch_database("story_mig114") as url:
        create_tables(
            url,
            story_tables(
                without={
                    "story_courses",
                    "story_course_bibles",
                    "story_module_plans",
                    "story_asset_catalogues",
                    "story_stock_art",
                    "story_seed_state",
                }
            ),
        )
        monkeypatch.setattr(settings, "database_url", url)
        config = Config()
        config.set_main_option("script_location", str(versions.parent))
        command.stamp(config, "104_add_ai_usage_events")
        command.upgrade(config, "109_story_art")

        engine = sync_engine(url)
        tables = Base.metadata.tables
        course_id = uuid.uuid4()
        row = {
            "id": uuid.uuid4(),
            "course_id": course_id,
            "kind": "place",
            "key": "market",
            "pose": "backdrop",
            "look_digest": "0" * 64,
            "status": "ready",
            "image_data": b"x",
        }
        try:
            with engine.begin() as conn:
                conn.execute(
                    tables["courses"]
                    .insert()
                    .values(id=course_id, slug="c-114", title_fr="C", title_en="C")
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO story_art (id, course_id, kind, key, pose, look_digest, status, image_data) VALUES (:id, :course_id, :kind, :key, :pose, :look_digest, :status, :image_data)"
                    ),
                    row,
                )
            command.upgrade(config, "114_story_stock_art")

            inspector = sa.inspect(engine)
            assert {"story_stock_art", "story_seed_state"} <= set(inspector.get_table_names())
            model_columns = {c.name for c in StoryStockArt.__table__.c}
            assert {c["name"] for c in inspector.get_columns("story_stock_art")} == model_columns
            assert "stock_id" in {c["name"] for c in inspector.get_columns("story_art")}
            with engine.begin() as conn:
                # The existing course's row is untouched.
                assert conn.execute(
                    sa.text("SELECT count(*), count(stock_id) FROM story_art")
                ).one() == (1, 0)
                # The extra poses are accepted now; an unknown pose is not.
                stock = uuid.uuid4()
                conn.execute(
                    sa.text(
                        "INSERT INTO story_stock_art (id, kind, theme, pose, image_data, content_sha256)"
                        " VALUES (:id, 'character', 'mentor', 'sad', 'x', :sha)"
                    ),
                    {"id": stock, "sha": "0" * 64},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO story_art (id, course_id, kind, key, pose, look_digest, status, stock_id)"
                        " VALUES (:id, :c, 'character', 'mentor', 'sad', :d, 'ready', :s)"
                    ),
                    {"id": uuid.uuid4(), "c": course_id, "d": "0" * 64, "s": stock},
                )
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                conn.execute(sa.text("DELETE FROM story_stock_art"))  # RESTRICT: a course uses it
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                conn.execute(
                    sa.text(
                        "INSERT INTO story_stock_art (id, kind, theme, pose, image_data, content_sha256)"
                        " VALUES (gen_random_uuid(), 'character', 'mentor', 'walk', 'x', 'y')"
                    )
                )

            command.downgrade(config, "113_story_asset_catalogues")
            inspector = sa.inspect(engine)
            assert "story_stock_art" not in inspector.get_table_names()
            assert "stock_id" not in {c["name"] for c in inspector.get_columns("story_art")}
            with engine.begin() as conn:
                # The course's own row survives the downgrade; the stock-backed one is gone.
                assert conn.execute(sa.text("SELECT count(*) FROM story_art")).scalar_one() == 1
            command.upgrade(config, "114_story_stock_art")
        finally:
            engine.dispose()
