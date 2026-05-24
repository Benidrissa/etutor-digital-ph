"""Backfill ``document_chunks.page`` for legacy RAG collections (#2058).

Chunks indexed before per-page chunking (#2039) have ``page=NULL``.  The
contextual image linker (``image_linker._build_contextual_pairs``) joins on
``chunk.page == image.page_number``; without page values that path yields zero
pairs regardless of how many images exist.

Approach (Option A — position-matched rewrite):
  For each PDF on disk, extract text per page (``extract_pages_from_pdf``),
  re-chunk each page with the same ``TextChunker`` settings, then match each
  new chunk back to an existing DB row by content-prefix fingerprint and write
  the page number.  Content and embeddings are never changed.

Usage:
    cd backend
    python scripts/backfill_chunk_pages.py                      # dry-run ALL
    python scripts/backfill_chunk_pages.py --apply              # apply ALL
    python scripts/backfill_chunk_pages.py --rag-collection-id <id>
    python scripts/backfill_chunk_pages.py --rag-collection-id <id> --apply

Idempotent: only processes chunks with ``page IS NULL``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

UPLOAD_DIR = Path("uploads/course_resources")
_FINGERPRINT_LEN = 150
_WHITESPACE = re.compile(r"\s+")


def _fingerprint(content: str) -> str:
    """Normalised prefix used for fuzzy content matching."""
    normalised = _WHITESPACE.sub(" ", content.lower()).strip()
    return normalised[:_FINGERPRINT_LEN]


async def _backfill_collection(
    session: AsyncSession,
    course_id: str,
    rag_collection_id: str,
    apply: bool,
) -> dict[str, int]:
    """Backfill page values for chunks in one RAG collection.

    Returns a stats dict: rewritten / unmatched / skipped.
    """
    stats = {"rewritten": 0, "unmatched": 0, "skipped": 0}

    # Only act on NULL-page chunks.
    chunk_rows = (
        await session.execute(
            text(
                "SELECT id, content FROM document_chunks "
                "WHERE source = :src AND page IS NULL "
                "ORDER BY id"
            ),
            {"src": rag_collection_id},
        )
    ).all()

    if not chunk_rows:
        return stats

    stats["skipped"] = len(chunk_rows)  # will subtract matched below

    course_dir = UPLOAD_DIR / course_id
    pdf_files = sorted(course_dir.glob("*.pdf")) if course_dir.exists() else []

    if not pdf_files:
        # No PDFs on disk — cannot determine page numbers.  Report all as unmatched.
        stats["skipped"] = 0
        stats["unmatched"] = len(chunk_rows)
        return stats

    # Build fingerprint → page map from all PDFs in the course directory.
    from app.ai.rag.chunker import TextChunker, extract_pages_from_pdf

    chunker = TextChunker()
    fingerprint_to_page: dict[str, int] = {}

    for pdf_path in pdf_files:
        try:
            pages = extract_pages_from_pdf(str(pdf_path))
        except Exception as exc:
            print(f"    WARN: cannot read {pdf_path.name}: {exc}")
            continue

        for page_num, page_text in pages:
            if not page_text.strip():
                continue
            for chunk in chunker.chunk_document(
                text=page_text,
                source=rag_collection_id,
                page=page_num,
            ):
                fp = _fingerprint(chunk.content)
                if fp and fp not in fingerprint_to_page:
                    fingerprint_to_page[fp] = page_num

    if not fingerprint_to_page:
        stats["skipped"] = 0
        stats["unmatched"] = len(chunk_rows)
        return stats

    # Match existing chunks to pages.
    updates: dict[int, list[str]] = {}  # page_num -> [chunk_id, ...]
    unmatched_ids: list[str] = []

    for chunk_id, content in chunk_rows:
        fp = _fingerprint(content)
        page = fingerprint_to_page.get(fp)
        if page is not None:
            updates.setdefault(page, []).append(str(chunk_id))
        else:
            unmatched_ids.append(str(chunk_id))

    stats["rewritten"] = sum(len(ids) for ids in updates.values())
    stats["unmatched"] = len(unmatched_ids)
    stats["skipped"] = 0

    if apply and updates:
        for page_num, chunk_ids in updates.items():
            await session.execute(
                text(
                    "UPDATE document_chunks SET page = :page WHERE id = ANY(:ids) AND page IS NULL"
                ),
                {"page": page_num, "ids": chunk_ids},
            )
        await session.commit()

    return stats


async def main(rag_collection_filter: str | None, apply: bool) -> int:
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:postgres@localhost:5432/santepublique",
    )
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"backfill_chunk_pages — {mode}")
    print("-" * 60)

    totals = {"rewritten": 0, "unmatched": 0, "skipped": 0}

    async with async_session() as session:
        if rag_collection_filter:
            # Single collection — find its course_id.
            row = (
                await session.execute(
                    text("SELECT id FROM courses WHERE rag_collection_id = :rag LIMIT 1"),
                    {"rag": rag_collection_filter},
                )
            ).first()
            if row is None:
                print(f"No course found for rag_collection_id={rag_collection_filter!r}")
                return 1
            collections = [(str(row[0]), rag_collection_filter)]
        else:
            # All courses that have any NULL-page chunks.
            rows = (
                await session.execute(
                    text(
                        "SELECT DISTINCT c.id, c.rag_collection_id "
                        "FROM courses c "
                        "JOIN document_chunks dc ON dc.source = c.rag_collection_id "
                        "WHERE c.rag_collection_id IS NOT NULL AND dc.page IS NULL"
                    )
                )
            ).all()
            collections = [(str(r[0]), r[1]) for r in rows]

    print(f"Collections to process: {len(collections)}")
    print()

    for course_id, rag_collection_id in collections:
        print(f"  course={course_id}  collection={rag_collection_id}")
        async with async_session() as session:
            stats = await _backfill_collection(session, course_id, rag_collection_id, apply)
        print(
            f"    rewritten={stats['rewritten']}  "
            f"unmatched={stats['unmatched']}  "
            f"skipped={stats['skipped']}"
        )
        for key in totals:
            totals[key] += stats[key]

    print()
    print("-" * 60)
    print(
        f"TOTAL  rewritten={totals['rewritten']}  "
        f"unmatched={totals['unmatched']}  "
        f"skipped={totals['skipped']}"
    )
    if not apply:
        print()
        print("Dry-run complete. Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--rag-collection-id",
        help="Process only this RAG collection (default: all collections with NULL-page chunks)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Write changes to DB (default is dry-run)",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.rag_collection_id, args.apply)))
