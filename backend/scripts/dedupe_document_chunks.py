"""Remove duplicate ``document_chunks`` produced by the donor-clone bug (#2542).

Before #2542, ``_find_donor_chunks`` matched donor chunks across *all* prior course
resources sharing a ``content_hash`` and cloned the union — multiplying a collection by
the number of earlier courses that used the same source PDF. The effect compounded:
a donor that was itself over-cloned got re-cloned, so counts grew ~2×, ~4×, … across
course generations (observed: a 846-unique-chunk PDF stored as 1658, then 3316 rows).

This script collapses each collection back to one row per logical chunk, keyed on
``(source, content, page, chunk_index)`` — the tuple that uniquely identifies a chunk
within a document. For every duplicate group it keeps the lowest ``id`` and deletes the
rest, first repointing any ``source_image_chunks`` (figure↔chunk) links from a deleted
row to the survivor so no image association is lost (the FK is ``ON DELETE CASCADE``).

No API spend — pure SQL. Idempotent: a second run finds nothing to do.

Usage:
    cd backend && python scripts/dedupe_document_chunks.py --dry-run
    cd backend && python scripts/dedupe_document_chunks.py --dry-run --source <rag_collection_id>
    cd backend && python scripts/dedupe_document_chunks.py            # apply to all sources
    cd backend && python scripts/dedupe_document_chunks.py --source <rag_collection_id>

Run --dry-run first, then apply on staging, verify counts, then prod after a fresh scan.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Duplicate rows within a source, keyed on the logical-chunk tuple. ``keeper_id`` is the
# lowest id in each group; every other row (rn > 1) is a duplicate to remove.
_BUILD_DUPE_MAP = """
CREATE TEMP TABLE _dupe_map ON COMMIT DROP AS
SELECT id AS dup_id, keeper_id
FROM (
    SELECT id,
           first_value(id) OVER w AS keeper_id,
           row_number()    OVER w AS rn
    FROM document_chunks
    {where}
    WINDOW w AS (
        PARTITION BY source, content, page, chunk_index
        ORDER BY id
    )
) ranked
WHERE rn > 1;
"""

# (a) Drop image links on a duplicate that would collide with an existing keeper link
#     (PK is (source_image_id, document_chunk_id)), so the repoint in (b) can't violate it.
_DROP_COLLIDING_LINKS = """
DELETE FROM source_image_chunks sic
USING _dupe_map m
WHERE sic.document_chunk_id = m.dup_id
  AND EXISTS (
      SELECT 1 FROM source_image_chunks k
      WHERE k.source_image_id = sic.source_image_id
        AND k.document_chunk_id = m.keeper_id
  );
"""

# (b) Repoint remaining image links from the duplicate to the surviving keeper.
_REPOINT_LINKS = """
UPDATE source_image_chunks sic
SET document_chunk_id = m.keeper_id
FROM _dupe_map m
WHERE sic.document_chunk_id = m.dup_id;
"""

# (c) Delete the duplicate chunks.
_DELETE_DUPES = """
DELETE FROM document_chunks dc
USING _dupe_map m
WHERE dc.id = m.dup_id;
"""

# Per-source before/after summary for the affected collections.
_AFFECTED_SUMMARY = """
SELECT dc.source,
       count(*) AS total_rows,
       count(*) FILTER (WHERE m.dup_id IS NOT NULL) AS dup_rows
FROM document_chunks dc
LEFT JOIN _dupe_map m ON m.dup_id = dc.id
{where}
GROUP BY dc.source
HAVING count(*) FILTER (WHERE m.dup_id IS NOT NULL) > 0
ORDER BY dup_rows DESC
"""


async def _run(session: AsyncSession, source: str | None, dry_run: bool) -> None:
    where = ""
    params: dict[str, str] = {}
    if source is not None:
        where = "WHERE source = :src"
        params["src"] = source

    await session.execute(text(_BUILD_DUPE_MAP.format(where=where)), params)

    dup_count = (
        await session.execute(text("SELECT count(*) FROM _dupe_map"))
    ).scalar_one()

    affected = (
        await session.execute(
            text(_AFFECTED_SUMMARY.format(where=where)), params
        )
    ).all()

    mode = "[dry-run]" if dry_run else "[applied]"
    for src, total, dups in affected:
        print(f"{mode} source={src}  total={total}  duplicates={dups}  -> keep={total - dups}")

    if dry_run:
        # Roll back the temp table + any reads; write nothing.
        await session.rollback()
        print(f"\n{mode} would remove {dup_count} duplicate chunk(s) across "
              f"{len(affected)} collection(s). No changes written.")
        return

    dropped = (await session.execute(text(_DROP_COLLIDING_LINKS))).rowcount
    repointed = (await session.execute(text(_REPOINT_LINKS))).rowcount
    deleted = (await session.execute(text(_DELETE_DUPES))).rowcount
    await session.commit()
    print(
        f"\n{mode} removed {deleted} duplicate chunk(s) across {len(affected)} "
        f"collection(s); repointed {repointed} image link(s), dropped "
        f"{dropped} colliding link(s)."
    )


async def main(source: str | None, dry_run: bool) -> int:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with async_session() as session:
            await _run(session, source, dry_run)
    finally:
        await engine.dispose()
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=None,
        help="Restrict to a single rag_collection_id (document_chunks.source). "
        "Default: every source with duplicates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be removed without writing.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args.source, args.dry_run)))
