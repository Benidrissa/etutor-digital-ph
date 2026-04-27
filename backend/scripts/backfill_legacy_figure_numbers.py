"""Backfill source_images.figure_number for legacy collections (#2055).

Pre-#2055 the image extractor used `(\\d+\\.?\\d*)` which truncated dashed
figure labels: "FIGURE 2-8 Pareto Chart" was stored as
``figure_number="FIGURE 2"`` with ``caption="8 Pareto Chart"`` — the
subnumber bled into the caption. The linker keys figure_map by the
extracted number, so every chapter-N image collapsed into one slot and
explicit matching effectively died (2/460 link rate on the test course).

This script repairs already-extracted rows in place — no PDF re-parse, no
MinIO writes, no re-embedding. It detects a leading-digit caption (the
characteristic signature of severed-subnumber rows) and folds those digits
back into figure_number, stripping the leading digit prefix from caption.

Usage::

    cd backend
    python scripts/backfill_legacy_figure_numbers.py \\
        --rag-collection-id 7eb5e3f5-192a-4953-8e87-840e09a0413e

    # Or run against every collection
    python scripts/backfill_legacy_figure_numbers.py --all

    # Dry-run (default). Add --apply to actually write
    python scripts/backfill_legacy_figure_numbers.py --all --apply

After this, call POST /api/v1/admin/courses/{id}/relink-images (#2044) on
each repaired course to materialize the new explicit pairs.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models.source_image import SourceImage  # noqa: E402

# Captures a leading multi-part number at the very start of the caption,
# allowing the same separators the linker normalizes ("-" or ".").
_LEADING_NUM = re.compile(r"^(\d+(?:[\.\-]\d+)*)")
# Used to validate that figure_number does NOT already include a subnumber.
# We only repair rows whose stored figure_number is chapter-only (e.g. "Figure 2").
_HAS_SUBNUMBER = re.compile(r"\d+[\.\-]\d+")


def _repair_one(figure_number: str | None, caption: str | None) -> tuple[str, str] | None:
    """Return (new_figure_number, new_caption) if the row should be repaired.

    None when the row is already well-formed or no recovery is possible.
    """
    if not figure_number or not caption:
        return None
    if _HAS_SUBNUMBER.search(figure_number):
        # Already has multi-part number — extractor was already correct
        # for this label, nothing to recover.
        return None
    m = _LEADING_NUM.match(caption)
    if not m:
        # Caption doesn't start with digits — figure was probably labeled
        # only at chapter granularity in the source PDF (e.g. "Figure 1"),
        # leave it alone.
        return None
    suffix = m.group(1)
    new_figure_number = f"{figure_number.rstrip()}-{suffix}"
    new_caption = caption[m.end() :].lstrip(" .:–—-")
    return new_figure_number, new_caption


async def backfill(rag_collection_id: str | None, apply: bool) -> None:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        stmt = select(SourceImage).where(SourceImage.figure_number.isnot(None))
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)

        result = await session.execute(stmt)
        rows = result.scalars().all()

        repaired = 0
        skipped_already_full = 0
        skipped_no_caption = 0
        skipped_no_leading_digit = 0

        for img in rows:
            fix = _repair_one(img.figure_number, img.caption)
            if fix is None:
                if not img.caption:
                    skipped_no_caption += 1
                elif _HAS_SUBNUMBER.search(img.figure_number or ""):
                    skipped_already_full += 1
                else:
                    skipped_no_leading_digit += 1
                continue

            new_figure_number, new_caption = fix
            print(
                f"  {img.id}  '{img.figure_number}' -> '{new_figure_number}'"
                f"   caption: '{(img.caption or '')[:50]}...' -> '{new_caption[:50]}...'"
            )
            if apply:
                img.figure_number = new_figure_number
                img.caption = new_caption
            repaired += 1

        if apply and repaired:
            await session.commit()
            print(f"\n[apply] Committed {repaired} updates.")
        else:
            print(f"\n[dry-run] Would repair {repaired} rows. Re-run with --apply to commit.")

        print(
            f"Summary: scanned={len(rows)} repaired={repaired} "
            f"already_full={skipped_already_full} no_caption={skipped_no_caption} "
            f"no_leading_digit={skipped_no_leading_digit}"
        )

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--rag-collection-id",
        help="Repair only this rag_collection_id (course's rag_collection_id).",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="Repair every collection in the database.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this flag the script is a dry-run.",
    )
    args = parser.parse_args()

    asyncio.run(
        backfill(
            rag_collection_id=None if args.all else args.rag_collection_id,
            apply=args.apply,
        )
    )


if __name__ == "__main__":
    main()
