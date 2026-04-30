"""Links SourceImage records to DocumentChunk records via the source_image_chunks junction table.

Three link types:
- explicit:   chunk text contains a "Figure X.Y" reference matching the
              image's figure_number
- contextual: image and chunk share the same page number (proximity),
              with chapter fallback for chunks whose `page` column is NULL
- semantic:   image embedding is close (cosine distance < threshold) to a
              chunk's embedding — catches the long tail of figures whose
              chunks paraphrase rather than cite by number (#2063)
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk

logger = structlog.get_logger(__name__)

# Match "Figure 1.5", "Fig 1-5", "Fig. 1.5.3", "FIGURE1.5", etc. The `.?\s*`
# lets the period-and-space after "Fig"/"Figure" be optional. The
# `(?:[\.\-]\d+)*` allows multi-part numbering ("1.5.3") rather than the
# previous two-part cap. (#2038)
_FIGURE_RE = re.compile(r"(?:Figure|Fig)\.?\s*(\d+(?:[\.\-]\d+)*)", re.IGNORECASE)

_PAGE_ADJACENCY = 1

# Semantic-similarity matcher tuning (#2063). The image embedding is
# generated from caption + figure_label in pipeline._process_images, the
# chunk embedding from chunk.content. Both are 1536-dim
# text-embedding-3-small vectors stored as double precision[] but cast to
# pgvector's `vector` type at query time (mirrors retriever.py's pattern).
#
# Defaults are conservative — preferring precision over recall. Tune by
# spot-checking pairs on the test course before relaxing.
_SEMANTIC_TOP_K = 3
_SEMANTIC_DIST_MAX = 0.35  # cosine distance; ~0.65 cosine similarity


def _normalize_figure_number(raw: str) -> str:
    """Normalise figure numbers so that '1-3' and '1.3' compare equal."""
    return raw.strip().replace("-", ".")


class ImageLinker:
    """Links images to text chunks for a given source document."""

    async def link_images_to_chunks(self, source: str, session: AsyncSession) -> int:
        """Create explicit, contextual, and semantic links between images and chunks.

        Args:
            source: The source identifier (e.g. "donaldson").
            session: Async SQLAlchemy session.

        Returns:
            Total number of new junction rows inserted.
        """
        explicit_pairs = await self._build_explicit_pairs(source, session)
        contextual_pairs = await self._build_contextual_pairs(source, session, explicit_pairs)
        # Semantic must run last so it can deduplicate against pairs the
        # higher-precision strategies already produced. It also needs to
        # dedupe against existing DB rows — explicit/contextual filter
        # against `_get_existing_pairs` internally, but semantic was
        # missing that check, so re-running the linker on an
        # already-linked course raised UniqueViolationError. See #2106.
        semantic_pairs = await self._build_semantic_pairs(
            source, session, explicit_pairs | contextual_pairs
        )

        rows: list[SourceImageChunk] = []
        for image_id, chunk_id in explicit_pairs:
            rows.append(
                SourceImageChunk(
                    source_image_id=image_id,
                    document_chunk_id=chunk_id,
                    reference_type="explicit",
                )
            )
        for image_id, chunk_id in contextual_pairs:
            rows.append(
                SourceImageChunk(
                    source_image_id=image_id,
                    document_chunk_id=chunk_id,
                    reference_type="contextual",
                )
            )
        for image_id, chunk_id in semantic_pairs:
            rows.append(
                SourceImageChunk(
                    source_image_id=image_id,
                    document_chunk_id=chunk_id,
                    reference_type="semantic",
                )
            )

        if rows:
            session.add_all(rows)
            await session.flush()

        logger.info(
            "image_linker.linked",
            source=source,
            explicit=len(explicit_pairs),
            contextual=len(contextual_pairs),
            semantic=len(semantic_pairs),
            total=len(rows),
        )
        return len(rows)

    async def clear_links_for_source(self, source: str, session: AsyncSession) -> int:
        """Delete all junction rows for images belonging to the given source.

        Args:
            source: The source identifier.
            session: Async SQLAlchemy session.

        Returns:
            Number of deleted rows.
        """
        image_ids_result = await session.execute(
            select(SourceImage.id).where(SourceImage.source == source)
        )
        image_ids = [row[0] for row in image_ids_result.all()]

        if not image_ids:
            return 0

        result = await session.execute(
            delete(SourceImageChunk).where(SourceImageChunk.source_image_id.in_(image_ids))
        )
        await session.flush()
        deleted = result.rowcount
        logger.info("image_linker.cleared", source=source, deleted=deleted)
        return deleted

    async def _build_explicit_pairs(self, source: str, session: AsyncSession) -> set[tuple]:
        """Scan chunk content for Figure references and match to images."""
        chunks_result = await session.execute(
            select(DocumentChunk.id, DocumentChunk.content).where(DocumentChunk.source == source)
        )
        chunks = chunks_result.all()

        images_result = await session.execute(
            select(SourceImage.id, SourceImage.figure_number).where(
                SourceImage.source == source,
                SourceImage.figure_number.isnot(None),
            )
        )
        figure_map: dict[str, object] = {}
        for image_id, figure_number in images_result.all():
            if figure_number:
                # Extract just the number from "Figure 1.2" -> "1.2"
                num_match = _FIGURE_RE.search(figure_number)
                raw = num_match.group(1) if num_match else figure_number
                key = _normalize_figure_number(raw)
                figure_map[key] = image_id

        existing_pairs = await self._get_existing_pairs(source, session)

        pairs: set[tuple] = set()
        for chunk_id, content in chunks:
            for match in _FIGURE_RE.finditer(content):
                figure_num = _normalize_figure_number(match.group(1))
                image_id = figure_map.get(figure_num)
                if image_id is not None:
                    pair = (image_id, chunk_id)
                    if pair not in existing_pairs:
                        pairs.add(pair)

        return pairs

    async def _build_contextual_pairs(
        self,
        source: str,
        session: AsyncSession,
        explicit_pairs: set[tuple],
    ) -> set[tuple]:
        """Find same-page image↔chunk pairs, skipping already-explicit ones.

        When a chunk's ``page`` is NULL, fall back to chapter-based matching so
        that the entire chapter's chunks are considered contextually linked to
        images whose ``chapter`` matches.  Page adjacency (±1) is applied when
        page information is available on both sides.
        """
        images_result = await session.execute(
            select(SourceImage.id, SourceImage.page_number, SourceImage.chapter).where(
                SourceImage.source == source
            )
        )
        images = images_result.all()

        chunks_with_page_result = await session.execute(
            select(DocumentChunk.id, DocumentChunk.page, DocumentChunk.chapter).where(
                DocumentChunk.source == source,
            )
        )
        chunks_all = chunks_with_page_result.all()

        page_to_chunks: dict[int, list] = {}
        chapter_to_chunks: dict[str, list] = {}
        null_page_chunks: list = []

        for chunk_id, page, chapter in chunks_all:
            if page is not None:
                for p in range(page - _PAGE_ADJACENCY, page + _PAGE_ADJACENCY + 1):
                    page_to_chunks.setdefault(p, []).append(chunk_id)
            else:
                null_page_chunks.append((chunk_id, chapter))
                if chapter:
                    chapter_to_chunks.setdefault(chapter, []).append(chunk_id)

        existing_pairs = await self._get_existing_pairs(source, session)
        explicit_image_chunk = {(img_id, c_id) for img_id, c_id in explicit_pairs}

        pairs: set[tuple] = set()
        for image_id, page_number, image_chapter in images:
            candidate_chunk_ids: list = list(page_to_chunks.get(page_number, []))

            if not candidate_chunk_ids and image_chapter:
                candidate_chunk_ids = list(chapter_to_chunks.get(image_chapter, []))

            for chunk_id in candidate_chunk_ids:
                pair = (image_id, chunk_id)
                if pair not in existing_pairs and pair not in explicit_image_chunk:
                    pairs.add(pair)

        return pairs

    async def _build_semantic_pairs(
        self,
        source: str,
        session: AsyncSession,
        higher_priority: set[tuple],
    ) -> set[tuple]:
        """Find image↔chunk pairs by embedding cosine similarity (#2063).

        Both ``source_images.embedding`` and ``document_chunks.embedding``
        are stored as ``double precision[]`` and cast to pgvector's
        ``vector`` type at query time (mirrors retriever.py's pattern,
        avoids schema migration). For each image, this returns up to
        ``_SEMANTIC_TOP_K`` chunk candidates whose cosine distance is
        below ``_SEMANTIC_DIST_MAX``. Pairs already in ``higher_priority``
        (existing junction rows + explicit + contextual) are deduplicated.

        Implementation note: the LATERAL JOIN runs the per-image
        top-K query in a single round-trip rather than 460 separate
        SELECTs. With pgvector's HNSW index on the embedding columns
        the inner ``ORDER BY <=> LIMIT K`` is sub-millisecond.

        Returns an empty set when either side has no embedded rows; the
        outer COUNT short-circuits the lateral join for collections that
        haven't been embedded yet.
        """
        # Skip the whole pass when the collection has no embedded chunks
        # or no embedded images — the join would just return zero rows
        # but the explicit COUNT short-circuits the round-trip.
        count_q = text(
            """
            SELECT
              (SELECT COUNT(*) FROM source_images
                 WHERE source = :src AND embedding IS NOT NULL) AS img_count,
              (SELECT COUNT(*) FROM document_chunks
                 WHERE source = :src AND embedding IS NOT NULL) AS chunk_count
            """
        ).bindparams(src=source)
        counts = (await session.execute(count_q)).one()
        if not (counts.img_count and counts.chunk_count):
            return set()

        # Per-image lateral query: pick top-K closest chunks above the
        # similarity threshold. The double `<=>` (one inside the LIMIT,
        # one in the projection) is intentional — pg planner only uses
        # the index for the ORDER BY clause.
        query = text(
            """
            SELECT si.id AS image_id,
                   cand.chunk_id,
                   cand.distance
              FROM source_images si
              CROSS JOIN LATERAL (
                SELECT dc.id AS chunk_id,
                       (si.embedding::vector <=> dc.embedding::vector) AS distance
                  FROM document_chunks dc
                 WHERE dc.source = :src
                   AND dc.embedding IS NOT NULL
                 ORDER BY si.embedding::vector <=> dc.embedding::vector
                 LIMIT :k
              ) AS cand
             WHERE si.source = :src
               AND si.embedding IS NOT NULL
               AND cand.distance < :max_dist
            """
        ).bindparams(src=source, k=_SEMANTIC_TOP_K, max_dist=_SEMANTIC_DIST_MAX)

        # Filter against rows already in the junction table so a re-run
        # of the linker doesn't try to insert duplicates. See #2106.
        existing_pairs = await self._get_existing_pairs(source, session)

        result = await session.execute(query)
        pairs: set[tuple] = set()
        for row in result.all():
            pair = (row.image_id, row.chunk_id)
            if pair in higher_priority or pair in existing_pairs:
                continue
            pairs.add(pair)

        return pairs

    async def _get_existing_pairs(self, source: str, session: AsyncSession) -> set[tuple]:
        """Return set of (source_image_id, document_chunk_id) pairs already in DB."""
        image_ids_result = await session.execute(
            select(SourceImage.id).where(SourceImage.source == source)
        )
        image_ids = [row[0] for row in image_ids_result.all()]

        if not image_ids:
            return set()

        existing_result = await session.execute(
            select(
                SourceImageChunk.source_image_id,
                SourceImageChunk.document_chunk_id,
            ).where(SourceImageChunk.source_image_id.in_(image_ids))
        )
        return {(row[0], row[1]) for row in existing_result.all()}
