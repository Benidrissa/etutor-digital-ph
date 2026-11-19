"""Seed the shared prop library from the pack bundled in the image (#2714).

Every stack (staging, production, each tenant) runs the same backend image, and
tenants are provisioned by another repository, so the library cannot depend on
a manual import or on the provisioner. The image carries the rendered library
(``app/data/story_library``: ``library.json`` and WebP files, built by the
asset foundry from CC0 models and committed); the API imports it **in the
background when it starts**:

* **Versioned.** ``library.json`` has a ``library_version``. The import runs
  when that version, or the file's sha256, differs from the one recorded in
  ``story_seed_state``; otherwise start-up costs one small query.
* **Idempotent.** An asset with unchanged pictures keeps its id (and its
  immutable URL); a changed one gets a new id; an asset of the bundle that is
  no longer in it is removed (never an asset an operator imported by hand).
* **Sticky misses reset.** When the version changes, every cached phrase match
  is cleared, so phrases that missed are matched against the new library.
* **Never blocks, never fails a start.** A task of its own, one worker at a
  time (a PostgreSQL advisory lock); any error, an empty bundle, a missing
  table or an unreachable database is logged and the API carries on.
* **No AI call.** The assets are not embedded; the matcher falls back to the
  head noun until an operator runs ``scripts/import_story_library.py`` (which
  embeds) on the same folder.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.models.story_prop_library import StoryLibraryAsset
from app.domain.models.story_stock_art import StorySeedState
from app.domain.services.story_library_import import (
    ImportPlan,
    apply_plan,
    load_folder,
    plan_import,
)

logger = structlog.get_logger(__name__)

SEED_NAME = "story_library"
#: Marks the assets this seed owns (``story_library_assets.source``).
BUNDLE_MARK = "bundle"
#: First key of the advisory lock (two int4 keys: namespace, seed).
LOCK_NAMESPACE = 0x2714
LOCK_KEY = 1
#: The library bundled in the image: ``backend/app/data/story_library``.
BUNDLE_DIR = Path(__file__).resolve().parents[2] / "data" / "story_library"


@dataclass
class SeedResult:
    status: str  # "seeded" | "up_to_date" | "no_bundle" | "empty" | "locked"
    version: int | None = None
    inserted: int = 0
    replaced: int = 0
    pruned: int = 0
    refused: int = 0


def read_bundle_version(folder: Path) -> tuple[int, str] | None:
    """``(library_version, sha256 of library.json)``, or None without a readable bundle."""
    path = folder / "library.json"
    try:
        raw = path.read_bytes()
        version = int(json.loads(raw).get("library_version") or 1)
    except (OSError, ValueError, AttributeError):
        return None
    return version, hashlib.sha256(raw).hexdigest()


async def seed_story_library(
    session_factory: async_sessionmaker[AsyncSession], folder: Path = BUNDLE_DIR
) -> SeedResult:
    """Import the bundled library when this stack has not applied this version yet."""
    bundle = read_bundle_version(folder)
    if bundle is None:
        return SeedResult("no_bundle")
    version, digest = bundle
    async with session_factory() as session:
        taken = (
            await session.execute(select(func.pg_try_advisory_xact_lock(LOCK_NAMESPACE, LOCK_KEY)))
        ).scalar()
        if not taken:
            return SeedResult("locked", version)
        state = (
            await session.execute(select(StorySeedState).where(StorySeedState.name == SEED_NAME))
        ).scalar_one_or_none()
        known = (
            await session.execute(
                select(func.count())
                .select_from(StoryLibraryAsset)
                .where(StoryLibraryAsset.source[BUNDLE_MARK].astext == SEED_NAME)
            )
        ).scalar_one()
        if (
            state is not None
            and state.version == version
            and state.content_sha256 == digest
            and known
        ):
            return SeedResult("up_to_date", version)

        incoming, refused = load_folder(folder)
        for line in refused:
            logger.warning("story_library_seed.refused", entry=line)
        if not incoming:
            return SeedResult("empty", version, refused=len(refused))
        for entry in incoming:
            entry.source = {**entry.source, BUNDLE_MARK: SEED_NAME}
        rows = await session.execute(
            select(
                StoryLibraryAsset.slug,
                StoryLibraryAsset.id,
                StoryLibraryAsset.content_sha256,
                StoryLibraryAsset.source,
            )
        )
        found = rows.all()
        plan: ImportPlan = plan_import(
            {slug: (row_id, sha) for slug, row_id, sha, _src in found}, incoming, prune=False
        )
        kept = {entry.slug for entry in incoming}
        plan.prune = [
            (row_id, slug)
            for slug, row_id, _sha, src in found
            if slug not in kept and (src or {}).get(BUNDLE_MARK) == SEED_NAME
        ]
        await apply_plan(session, plan, {})  # also clears every cached phrase match
        if state is None:
            session.add(StorySeedState(name=SEED_NAME, version=version, content_sha256=digest))
        else:
            state.version, state.content_sha256 = version, digest
            state.applied_at = func.now()
        await session.commit()
    return SeedResult(
        "seeded",
        version,
        inserted=len(plan.insert),
        replaced=len(plan.replace),
        pruned=len(plan.prune),
        refused=len(refused),
    )


async def run_story_library_seed(
    session_factory: async_sessionmaker[AsyncSession] | None = None, folder: Path = BUNDLE_DIR
) -> SeedResult | None:
    """:func:`seed_story_library`, logging instead of raising (start-up never fails)."""
    try:
        if session_factory is None:
            from app.infrastructure.persistence.database import async_session_factory

            session_factory = async_session_factory
        result = await seed_story_library(session_factory, folder)
    except Exception as exc:
        logger.warning("story_library_seed.skipped", error=f"{type(exc).__name__}: {exc}"[:300])
        return None
    logger.info("story_library_seed.done", **result.__dict__)
    return result


__all__ = ("BUNDLE_DIR", "SeedResult", "run_story_library_seed", "seed_story_library")
