"""Backfill ``document_chunks.course_resource_id`` from chunk content (#2190).

Migration 089 added ``course_resource_id`` (nullable FK to ``course_resources.id``)
to ``document_chunks``. New chunks land with the FK populated by ingest. Existing
chunks have NULL FK; this script populates them by fingerprint-matching each
chunk's content against the originating course's ``CourseResource.raw_text``.

No API spend — pure SQL + Python (same logic as ``citation_formatter._normalize_for_match``).
Ambiguous chunks (content matches multiple resources, e.g. shared boilerplate)
keep ``course_resource_id = NULL`` and continue to use the read-side tiebreaker.

Usage:
    cd backend && python scripts/backfill_chunk_resource_ids.py
    cd backend && python scripts/backfill_chunk_resource_ids.py --course-id <UUID>
    cd backend && python scripts/backfill_chunk_resource_ids.py --dry-run

Idempotent. Re-running only acts on still-NULL rows.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict
from typing import Any
from uuid import UUID

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Mirror citation_formatter._normalize_for_match — keep the two implementations
# in sync if either changes.
_PAGE_NUMBER_NOISE = re.compile(r"\b(?:Page|page)\s*\d+\b")
_CHAPTER_HEADER_NOISE = re.compile(r"\b\d{1,3}\s*\|\s*Chapter\s*\d+")
_CASE_BREAK = re.compile(r"([a-z])([A-Z])")
_WHITESPACE = re.compile(r"\s+")
_FINGERPRINT_LEN = 200


def _normalize_for_match(text_in: str | None) -> str:
    if not text_in:
        return ""
    text_in = _WHITESPACE.sub(" ", text_in)
    text_in = _PAGE_NUMBER_NOISE.sub("", text_in)
    text_in = _CHAPTER_HEADER_NOISE.sub("", text_in)
    text_in = re.sub(r"\s*\n\s*", " ", text_in)
    text_in = _CASE_BREAK.sub(r"\1. \2", text_in)
    return text_in.lower()


async def _backfill_course(
    session: AsyncSession,
    course_id: UUID,
    rag_collection_id: str,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Backfill chunks for a single course.

    Returns ``(scanned, updated, ambiguous)``.
    """
    # Load all resources with their raw_text once.
    res_rows = (
        await session.execute(
            text(
                "SELECT id, raw_text FROM course_resources "
                "WHERE course_id = :cid AND raw_text IS NOT NULL"
            ),
            {"cid": str(course_id)},
        )
    ).all()
    if len(res_rows) < 2:
        # Single-resource: read-side already maps everything to the only PDF;
        # nothing to disambiguate at the chunk level.
        return 0, 0, 0

    normalized_resources: list[tuple[Any, str]] = [
        (r[0], _normalize_for_match(r[1])) for r in res_rows
    ]

    # Load chunks needing backfill.
    chunk_rows = (
        await session.execute(
            text(
                "SELECT id, content FROM document_chunks "
                "WHERE source = :rag AND course_resource_id IS NULL"
            ),
            {"rag": rag_collection_id},
        )
    ).all()

    scanned = len(chunk_rows)
    if scanned == 0:
        return 0, 0, 0

    # Bucket chunks by their resolved resource id (if unique).
    updates: dict[Any, list[Any]] = defaultdict(list)
    ambiguous = 0
    for chunk_id, content in chunk_rows:
        normalized = _normalize_for_match(content)
        fingerprint = normalized[:_FINGERPRINT_LEN]
        if len(fingerprint) < 40:
            ambiguous += 1
            continue
        matches = [rid for (rid, t) in normalized_resources if fingerprint in t]
        if len(matches) == 1:
            updates[matches[0]].append(chunk_id)
        else:
            ambiguous += 1

    updated = sum(len(ids) for ids in updates.values())
    if dry_run or not updates:
        return scanned, updated, ambiguous

    # Apply updates per-resource (single round-trip per resource).
    for resource_id, chunk_ids in updates.items():
        await session.execute(
            text(
                "UPDATE document_chunks SET course_resource_id = :rid "
                "WHERE id = ANY(:ids) AND course_resource_id IS NULL"
            ),
            {"rid": resource_id, "ids": chunk_ids},
        )
    await session.commit()
    return scanned, updated, ambiguous


async def main(course_filter: UUID | None, dry_run: bool) -> int:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    total_scanned = 0
    total_updated = 0
    total_ambiguous = 0
    courses_processed = 0

    async with async_session() as session:
        # Find candidate courses: have rag_collection_id AND >1 CourseResource.
        course_query = """
            SELECT c.id, c.rag_collection_id
            FROM courses c
            WHERE c.rag_collection_id IS NOT NULL
              AND (
                  SELECT COUNT(*) FROM course_resources cr
                  WHERE cr.course_id = c.id AND cr.raw_text IS NOT NULL
              ) >= 2
        """
        params: dict[str, Any] = {}
        if course_filter is not None:
            course_query += " AND c.id = :cid"
            params["cid"] = str(course_filter)

        course_rows = (await session.execute(text(course_query), params)).all()
        if not course_rows:
            print(
                "No multi-resource courses to backfill"
                + (f" (course filter: {course_filter})" if course_filter else "")
            )
            return 0

        for c_id, rag_id in course_rows:
            scanned, updated, ambiguous = await _backfill_course(session, c_id, rag_id, dry_run)
            if scanned == 0:
                continue
            courses_processed += 1
            total_scanned += scanned
            total_updated += updated
            total_ambiguous += ambiguous
            mode = "[dry-run]" if dry_run else "[applied]"
            print(
                f"{mode} course={c_id}  scanned={scanned}  updated={updated}  ambiguous={ambiguous}"
            )

    await engine.dispose()

    print(
        f"\nDone. courses_processed={courses_processed}  "
        f"chunks_scanned={total_scanned}  chunks_updated={total_updated}  "
        f"ambiguous_left_null={total_ambiguous}  dry_run={dry_run}"
    )
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--course-id",
        type=UUID,
        default=None,
        help="Restrict backfill to a single course UUID. Default: all multi-resource courses.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be updated without writing.",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(asyncio.run(main(args.course_id, args.dry_run)))
