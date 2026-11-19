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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.models.story_prop_library import StoryLibraryAsset  # noqa: E402
from app.domain.services.story_library_import import (  # noqa: E402, F401
    ImportPlan,
    Incoming,
    apply_plan,
    licence_problem,
    load_folder,
    plan_import,
    reset_misses,
)
from app.domain.services.story_prop_library import embedding_text  # noqa: E402


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
