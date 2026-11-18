#!/usr/bin/env python3
"""Import the asset foundry's output into the story prop library (Phase A).

docs/story-mode-3d-assets.md: the foundry (``infrastructure/asset-foundry``)
renders free 3D models into stickers and close-ups and writes them, with
``library.json``, into one folder. This script loads that folder into
``story_library_assets``, so the story routes can serve the pictures:

* an entry is refused when the library may not serve it: a licence outside
  CC0, PD, CC BY and CC BY-SA, a share-alike sticker, no credit line, no
  source page, or a missing picture (the foundry's gate, checked again here,
  the last step before learners see it);
* a slug already imported with the same pictures keeps its id (and URL);
  changed pictures get a new id, so the immutable URLs never change meaning;
* ``--prune`` deletes the assets whose slug is no longer in the folder;
* each imported asset's label and tags are embedded for the matcher
  (``--no-embed`` to skip, e.g. without an OpenAI key);
* the cached phrase matches are cleared: every phrase is matched again,
  against the new library, the next time a story using it is viewed.

Usage (inside the backend container, after copying the folder in)::

    python scripts/import_story_library.py /tmp/library --dry-run
    python scripts/import_story_library.py /tmp/library --prune
    python scripts/import_story_library.py --reset-misses      # no folder needed

``--reset-misses`` deletes only the cached misses (phrases that matched no
asset), so each is matched again on its next view (#2708). A miss older than
the newest asset is matched again on its own; this is for forcing it.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, func, select, update  # noqa: E402

from app.domain.models.story_prop_library import (  # noqa: E402
    ASSET_KINDS,
    ASSET_STICKER,
    StoryLibraryAsset,
    StoryPropMatch,
)
from app.domain.services.story_prop_library import embedding_text  # noqa: E402

_PUBLIC = re.compile(r"^(CC0-1\.0|PDM)$")
_BY = re.compile(r"^CC-BY-[1-4]\.0$")
_BY_SA = re.compile(r"^CC-BY-SA-[1-4]\.0$")
_SLUG = re.compile(r"^[a-z0-9_]{1,60}$")


def licence_problem(kind: str, licence: str) -> str | None:
    """Why the library may not serve this licence for this kind, or None."""
    if _PUBLIC.match(licence) or _BY.match(licence):
        return None
    if _BY_SA.match(licence):
        return "share-alike is close-up only" if kind == ASSET_STICKER else None
    return f"licence {licence or '(none)'} is not served"


@dataclass
class Incoming:
    """One entry of library.json with its pictures read."""

    slug: str
    kind: str
    label: dict[str, str]
    tags: list[str]
    image: bytes
    image_large: bytes | None
    width: int
    height: int
    licence: str
    attribution_required: bool
    credit: dict[str, str]
    source: dict[str, Any]
    library_version: int

    @property
    def sha256(self) -> str:
        digest = hashlib.sha256(self.image)
        digest.update(self.image_large or b"")
        return digest.hexdigest()


def load_folder(folder: Path) -> tuple[list[Incoming], list[str]]:
    """The accepted entries of ``folder/library.json``, and why the others were refused."""
    library = json.loads((folder / "library.json").read_text(encoding="utf-8"))
    version = int(library.get("library_version") or 1)
    accepted: list[Incoming] = []
    refused: list[str] = []
    seen: set[str] = set()
    for entry in library.get("entries") or []:
        slug = str(entry.get("id") or "")
        kind = str(entry.get("kind") or "")
        licence = str(entry.get("licence") or "")
        credit = entry.get("credit") if isinstance(entry.get("credit"), dict) else {}
        source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
        files = entry.get("files") if isinstance(entry.get("files"), dict) else {}
        problem = None
        if not _SLUG.match(slug) or slug in seen:
            problem = "bad or repeated id"
        elif kind not in ASSET_KINDS:
            problem = f"unknown kind {kind!r}"
        else:
            problem = licence_problem(kind, licence)
        if not problem and not (credit.get("en") and credit.get("fr")):
            problem = "no credit line in both languages"
        if not problem and not source.get("page"):
            problem = "no source page"
        small = folder / str((files.get("src") or {}).get("file") or "")
        large_name = (files.get("src_large") or {}).get("file")
        large = folder / str(large_name) if large_name else None
        if not problem and (not small.is_file() or (large is not None and not large.is_file())):
            problem = "picture file missing"
        if problem:
            refused.append(f"{slug or '?'}: {problem}")
            continue
        seen.add(slug)
        label = entry.get("label") if isinstance(entry.get("label"), dict) else {}
        accepted.append(
            Incoming(
                slug=slug,
                kind=kind,
                label={"en": str(label.get("en") or slug), "fr": str(label.get("fr") or slug)},
                tags=[str(tag) for tag in entry.get("tags") or [] if str(tag).strip()],
                image=small.read_bytes(),
                image_large=large.read_bytes() if large else None,
                width=int(entry.get("width") or 0),
                height=int(entry.get("height") or 0),
                licence=licence,
                attribution_required=bool(entry.get("attribution_required")),
                credit={"en": str(credit["en"]), "fr": str(credit["fr"])},
                source=dict(source),
                library_version=version,
            )
        )
    return accepted, refused


@dataclass
class ImportPlan:
    insert: list[Incoming] = field(default_factory=list)
    #: Changed pictures: the old row goes, a new id comes.
    replace: list[tuple[uuid.UUID, Incoming]] = field(default_factory=list)
    #: Same pictures: the id stays, the metadata is refreshed.
    refresh: list[tuple[uuid.UUID, Incoming]] = field(default_factory=list)
    prune: list[tuple[uuid.UUID, str]] = field(default_factory=list)


def plan_import(
    existing: dict[str, tuple[uuid.UUID, str]], incoming: list[Incoming], *, prune: bool
) -> ImportPlan:
    """What to do with each slug, given ``existing`` (slug → (id, content sha256))."""
    plan = ImportPlan()
    for entry in incoming:
        current = existing.get(entry.slug)
        if current is None:
            plan.insert.append(entry)
        elif current[1] != entry.sha256:
            plan.replace.append((current[0], entry))
        else:
            plan.refresh.append((current[0], entry))
    if prune:
        kept = {entry.slug for entry in incoming}
        plan.prune = [
            (row_id, slug) for slug, (row_id, _sha) in existing.items() if slug not in kept
        ]
    return plan


def _values(entry: Incoming) -> dict[str, Any]:
    return {
        "kind": entry.kind,
        "label": entry.label,
        "tags": entry.tags,
        "width": entry.width,
        "height": entry.height,
        "bytes": len(entry.image),
        "licence": entry.licence,
        "attribution_required": entry.attribution_required,
        "credit": entry.credit,
        "source": entry.source,
        "library_version": entry.library_version,
    }


async def apply_plan(session, plan: ImportPlan, embeddings: dict[str, list[float]]) -> None:
    """Write ``plan``: deletes first (a replaced slug frees its unique slug), then writes."""
    gone = [row_id for row_id, _entry in plan.replace] + [row_id for row_id, _slug in plan.prune]
    if gone:
        await session.execute(delete(StoryLibraryAsset).where(StoryLibraryAsset.id.in_(gone)))
    for entry in [*plan.insert, *(entry for _id, entry in plan.replace)]:
        session.add(
            StoryLibraryAsset(
                id=uuid.uuid4(),
                slug=entry.slug,
                image_data=entry.image,
                image_large=entry.image_large,
                content_sha256=entry.sha256,
                embedding=embeddings.get(entry.slug),
                **_values(entry),
            )
        )
    for row_id, entry in plan.refresh:
        values = _values(entry)
        if entry.slug in embeddings:
            values["embedding"] = embeddings[entry.slug]
        await session.execute(
            update(StoryLibraryAsset).where(StoryLibraryAsset.id == row_id).values(**values)
        )
    # Every phrase is matched again, against this library.
    await session.execute(delete(StoryPropMatch))


async def embed_entries(entries: list[Incoming]) -> dict[str, list[float]]:
    """text-embedding-3-small of each entry's label and tags, by slug."""
    from app.ai.rag.embeddings import EmbeddingService
    from app.infrastructure.config.settings import settings

    if not entries:
        return {}
    if not settings.openai_api_key:
        raise RuntimeError("no OpenAI key: run with --no-embed")
    service = EmbeddingService(api_key=settings.openai_api_key)
    texts = [embedding_text(entry.slug, entry.label, entry.tags) for entry in entries]
    vectors = await service.generate_embeddings_batch(texts)
    return {entry.slug: vector for entry, vector in zip(entries, vectors, strict=True)}


async def reset_misses(session, *, dry_run: bool = False) -> int:
    """Delete the cached misses (``asset_id`` NULL); return how many there were."""
    count = (
        await session.execute(
            select(func.count())
            .select_from(StoryPropMatch)
            .where(StoryPropMatch.asset_id.is_(None))
        )
    ).scalar_one()
    if dry_run:
        print(f"Dry run: {count} cached misses would be cleared.")
        return int(count)
    await session.execute(delete(StoryPropMatch).where(StoryPropMatch.asset_id.is_(None)))
    print(f"{count} cached misses cleared: those phrases are matched again on their next view.")
    return int(count)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "folder",
        nargs="?",
        help="the foundry's output folder (library.json and WebP files)",
    )
    parser.add_argument(
        "--reset-misses",
        action="store_true",
        help="delete the cached phrase misses (no asset), so they are matched again "
        "(alone: no folder needed; an import already clears every match)",
    )
    parser.add_argument(
        "--prune", action="store_true", help="delete assets missing from the folder"
    )
    parser.add_argument("--no-embed", action="store_true", help="skip the embeddings")
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None, embed=None) -> int:
    args = parse_args(argv)
    if args.folder is None:
        if not args.reset_misses:
            print("a folder, or --reset-misses, is needed", file=sys.stderr)
            return 2
        if session_factory is None:
            from app.infrastructure.persistence.database import async_session_factory

            session_factory = async_session_factory
        async with session_factory() as session:
            await reset_misses(session, dry_run=args.dry_run)
            if not args.dry_run:
                await session.commit()
        return 0
    folder = Path(args.folder)
    if not (folder / "library.json").is_file():
        print(f"{folder}/library.json not found", file=sys.stderr)
        return 2
    incoming, refused = load_folder(folder)
    for line in refused:
        print(f"refused {line}")
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    async with session_factory() as session:
        rows = await session.execute(
            select(StoryLibraryAsset.slug, StoryLibraryAsset.id, StoryLibraryAsset.content_sha256)
        )
        existing = {slug: (row_id, sha) for slug, row_id, sha in rows.all()}
        plan = plan_import(existing, incoming, prune=args.prune)
        print(
            f"{len(incoming)} accepted, {len(refused)} refused: {len(plan.insert)} new, "
            f"{len(plan.replace)} replaced, {len(plan.refresh)} unchanged pictures, "
            f"{len(plan.prune)} pruned"
        )
        if args.dry_run:
            print("Dry run: nothing written.")
            return 0
        embeddings: dict[str, list[float]] = {}
        if not args.no_embed:
            embeddings = await (embed or embed_entries)(incoming)
        await apply_plan(session, plan, embeddings)
        await session.commit()
    print("Imported. Cached phrase matches cleared: phrases are matched again on their next view.")
    return 1 if refused and not incoming else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
