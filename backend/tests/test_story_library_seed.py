"""The bundled prop library and its automatic seed (#2714).

The bundle is the real committed pack (``app/data/story_library``): its
integrity and licences are checked here, so a bad asset never reaches a
stack. The seed itself runs on a scratch PostgreSQL database (skipped when no
server is reachable) with temporary folders; it makes no AI call.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

from app.domain.models.story_prop_library import StoryLibraryAsset, StoryPropMatch
from app.domain.models.story_stock_art import StorySeedState
from app.domain.services import story_library_seed as seed
from app.domain.services.story_library_import import licence_problem, load_folder

BUNDLE = seed.BUNDLE_DIR
FOUNDRY_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "asset-foundry"
    / "library"
    / "manifest.json"
)


class TestTheBundledPack:
    @pytest.fixture(scope="class")
    def library(self):
        return json.loads((BUNDLE / "library.json").read_text(encoding="utf-8"))

    def test_it_is_versioned(self, library):
        assert isinstance(library["library_version"], int) and library["library_version"] >= 1
        assert seed.read_bundle_version(BUNDLE)[0] == library["library_version"]

    def test_it_is_a_real_library(self, library):
        assert len(library["entries"]) >= 100

    def test_every_entry_is_accepted_by_the_importer(self):
        accepted, refused = load_folder(BUNDLE)
        assert refused == []
        assert len(accepted) >= 100

    def test_every_licence_is_cc0_with_its_evidence(self, library):
        for entry in library["entries"]:
            source = entry["source"]
            assert entry["licence"] == "CC0-1.0" and source["license"] == "CC0-1.0", entry["id"]
            assert licence_problem(entry["kind"], entry["licence"]) is None
            assert entry["kind"] == "sticker"
            assert source["author"] in {"Quaternius", "Kenney"}, entry["id"]
            assert re.fullmatch(r"https://poly\.pizza/m/[A-Za-z0-9_-]+", source["page"]), entry[
                "id"
            ]
            assert (
                "CC0 1.0" in source["licence_read"] and source["author"] in source["licence_read"]
            )
            assert re.fullmatch(r"[0-9a-f]{64}", source["sha256_original"]), entry["id"]
            assert entry["credit"]["en"] and entry["credit"]["fr"]
            assert not entry["attribution_required"]

    def test_slugs_are_unique_and_the_files_exist_and_are_small(self, library):
        slugs = [e["id"] for e in library["entries"]]
        assert len(slugs) == len(set(slugs))
        total = 0
        for entry in library["entries"]:
            path = BUNDLE / entry["files"]["src"]["file"]
            data = path.read_bytes()
            assert data[:4] == b"RIFF" and data[8:12] == b"WEBP", entry["id"]
            assert len(data) <= 40_000, entry["id"]
            assert max(entry["width"], entry["height"]) <= 400
            total += len(data)
        assert total < 3_000_000  # the whole library rides in the image: stays small
        assert {p.name for p in BUNDLE.glob("*.webp")} == {
            e["files"]["src"]["file"] for e in library["entries"]
        }

    def test_it_matches_the_foundry_manifest(self, library):
        manifest = json.loads(FOUNDRY_MANIFEST.read_text(encoding="utf-8"))
        assert manifest["library_version"] == library["library_version"]
        assert {e["id"] for e in manifest["entries"]} == {e["id"] for e in library["entries"]}
        by_id = {e["id"]: e for e in library["entries"]}
        for entry in manifest["entries"]:
            built = by_id[entry["id"]]
            assert built["source"]["page"] == entry["source"]["page"]
            assert built["model_sha256"] == entry["source"]["sha256_original"]
            assert built["label"] == entry["label"]

    def test_no_non_cc0_or_unknown_author_in_the_manifest(self):
        manifest = json.loads(FOUNDRY_MANIFEST.read_text(encoding="utf-8"))
        for entry in manifest["entries"]:
            assert entry["source"]["license"] == "CC0-1.0"
            assert entry["source"]["author"] in {"Quaternius", "Kenney"}


class TestReadBundleVersion:
    def test_missing_or_broken_bundles(self, tmp_path):
        assert seed.read_bundle_version(tmp_path) is None
        (tmp_path / "library.json").write_text("not json")
        assert seed.read_bundle_version(tmp_path) is None

    def test_version_defaults_to_one(self, tmp_path):
        (tmp_path / "library.json").write_text('{"entries": []}')
        assert seed.read_bundle_version(tmp_path)[0] == 1


async def test_a_failing_seed_never_raises():
    class Broken:
        def __call__(self):
            raise ConnectionRefusedError("database down")

    assert await seed.run_story_library_seed(Broken(), BUNDLE) is None


async def test_no_bundle_is_not_an_error(tmp_path):
    assert (await seed.run_story_library_seed(object(), tmp_path)).status == "no_bundle"


# -- PostgreSQL ---------------------------------------------------------------------

_WEBP = None


def _webp(colour=(10, 120, 40, 255)) -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGBA", (20, 20), colour).save(out, format="WEBP")
    return out.getvalue()


def _write_pack(folder: Path, slugs: list[str], *, version: int = 1, colour=(10, 120, 40, 255)):
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for slug in slugs:
        (folder / f"{slug}.webp").write_bytes(_webp(colour))
        entries.append(
            {
                "id": slug,
                "kind": "sticker",
                "label": {"en": f"a {slug}", "fr": f"un {slug}"},
                "tags": [slug],
                "files": {"src": {"file": f"{slug}.webp"}},
                "width": 20,
                "height": 20,
                "licence": "CC0-1.0",
                "attribution_required": False,
                "credit": {"en": "3D model (CC0 1.0)", "fr": "Modele 3D (CC0 1.0)"},
                "source": {
                    "author": "Quaternius",
                    "license": "CC0-1.0",
                    "page": "https://poly.pizza/m/x",
                },
            }
        )
    (folder / "library.json").write_text(
        json.dumps({"library_version": version, "entries": entries})
    )


def _db(scenario):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.models import Base
    from tests._story_db import create_tables, scratch_database, story_tables

    with scratch_database("story_seed") as url:
        create_tables(
            url,
            [
                *story_tables(),
                Base.metadata.tables["story_library_assets"],
                Base.metadata.tables["story_prop_matches"],
            ],
        )

        async def run():
            engine = create_async_engine(url)
            maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                await scenario(maker)
            finally:
                await engine.dispose()

        asyncio.run(run())


async def _slugs(maker) -> dict[str, uuid.UUID]:
    async with maker() as session:
        rows = await session.execute(sa.select(StoryLibraryAsset.slug, StoryLibraryAsset.id))
        return {slug: row_id for slug, row_id in rows.all()}


def test_on_postgres_the_real_bundle_seeds_an_empty_stack_then_costs_one_query():
    async def scenario(maker):
        first = await seed.seed_story_library(maker)
        accepted, _ = load_folder(BUNDLE)
        assert first.status == "seeded" and first.inserted == len(accepted)
        slugs = await _slugs(maker)
        assert len(slugs) == len(accepted)
        async with maker() as session:
            state = (await session.execute(sa.select(StorySeedState))).scalar_one()
            assert state.version == first.version and len(state.content_sha256) == 64
            marked = (
                await session.execute(
                    sa.select(sa.func.count()).where(
                        StoryLibraryAsset.source["bundle"].astext == "story_library"
                    )
                )
            ).scalar_one()
            assert marked == len(accepted)
        again = await seed.seed_story_library(maker)
        assert again.status == "up_to_date"
        assert await _slugs(maker) == slugs  # same ids, same URLs

    _db(scenario)


def test_on_postgres_a_new_version_resets_misses_keeps_unchanged_urls_and_prunes_only_the_bundle(
    tmp_path,
):
    async def scenario(maker):
        pack = tmp_path / "pack"
        _write_pack(pack, ["bucket", "chair", "stool"], version=1)
        assert (await seed.seed_story_library(maker, pack)).inserted == 3
        before = await _slugs(maker)
        async with maker() as session:
            # An asset an operator imported by hand, and two cached phrase results.
            session.add(
                StoryLibraryAsset(
                    id=uuid.uuid4(),
                    slug="by_hand",
                    kind="sticker",
                    label={"en": "x", "fr": "x"},
                    image_data=_webp(),
                    width=20,
                    height=20,
                    bytes=10,
                    content_sha256="0" * 64,
                    licence="CC0-1.0",
                    attribution_required=False,
                    credit={"en": "c", "fr": "c"},
                    source={"author": "me"},
                )
            )
            session.add(
                StoryPropMatch(query="a drum", prop_kind="sticker", asset_id=None, method="lexical")
            )
            await session.commit()

        # Version 2: chair replaced by new pictures, stool gone, table new.
        _write_pack(pack, ["bucket", "table"], version=2)
        (pack / "chair.webp").unlink(missing_ok=True)
        result = await seed.seed_story_library(maker, pack)
        assert (result.status, result.inserted, result.pruned) == ("seeded", 1, 2)
        after = await _slugs(maker)
        assert set(after) == {"bucket", "table", "by_hand"}  # the hand-imported one stays
        assert after["bucket"] == before["bucket"]  # unchanged pictures keep their URL
        async with maker() as session:
            assert (
                await session.execute(sa.select(sa.func.count()).select_from(StoryPropMatch))
            ).scalar_one() == 0
            state = (await session.execute(sa.select(StorySeedState))).scalar_one()
            assert state.version == 2

    _db(scenario)


def test_on_postgres_a_version_bump_with_no_asset_change_still_clears_the_sticky_misses(tmp_path):
    async def scenario(maker):
        pack = tmp_path / "pack"
        _write_pack(pack, ["bucket"], version=1)
        await seed.seed_story_library(maker, pack)
        async with maker() as session:
            session.add(
                StoryPropMatch(query="a drum", prop_kind="sticker", asset_id=None, method="lexical")
            )
            await session.commit()
        _write_pack(pack, ["bucket"], version=2)
        result = await seed.seed_story_library(maker, pack)
        assert result.status == "seeded" and result.inserted == 0
        async with maker() as session:
            assert (
                await session.execute(sa.select(sa.func.count()).select_from(StoryPropMatch))
            ).scalar_one() == 0

    _db(scenario)


def test_on_postgres_an_empty_or_refused_pack_does_not_fail_and_changes_nothing(tmp_path):
    async def scenario(maker):
        pack = tmp_path / "pack"
        _write_pack(pack, [], version=1)
        assert (await seed.seed_story_library(maker, pack)).status == "empty"
        # Every entry refused (a licence outside the gate): still no error, nothing written.
        _write_pack(pack, ["bucket"], version=2)
        data = json.loads((pack / "library.json").read_text())
        data["entries"][0]["licence"] = "CC-BY-NC-4.0"
        (pack / "library.json").write_text(json.dumps(data))
        result = await seed.seed_story_library(maker, pack)
        assert result.status == "empty" and result.refused == 1
        assert await _slugs(maker) == {}
        async with maker() as session:
            assert (
                await session.execute(sa.select(sa.func.count()).select_from(StorySeedState))
            ).scalar_one() == 0

    _db(scenario)


def test_on_postgres_a_second_worker_holding_the_lock_skips(tmp_path):
    async def scenario(maker):
        pack = tmp_path / "pack"
        _write_pack(pack, ["bucket"])
        async with maker() as holder:
            await holder.execute(
                sa.select(sa.func.pg_advisory_xact_lock(seed.LOCK_NAMESPACE, seed.LOCK_KEY))
            )
            assert (await seed.seed_story_library(maker, pack)).status == "locked"
        assert (await seed.seed_story_library(maker, pack)).status == "seeded"

    _db(scenario)


def test_on_postgres_a_tenant_database_without_the_tables_logs_and_carries_on(tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tests._story_db import scratch_database

    with scratch_database("story_seed_empty") as url:

        async def run():
            engine = create_async_engine(url)
            maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            try:
                return await seed.run_story_library_seed(maker, BUNDLE)
            finally:
                await engine.dispose()

        assert (
            asyncio.run(run()) is None
        )  # tables missing (migrations pending): skipped, not raised
