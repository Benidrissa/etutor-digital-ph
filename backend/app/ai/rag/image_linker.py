"""Links SourceImage records to DocumentChunk records via the source_image_chunks junction table.

Two link types:
- explicit: chunk text contains a "Figure X.Y" reference matching the image's figure_number
- contextual: image and chunk share the same page number (proximity), with chapter fallback
  for chunks whose `page` column is NULL
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk

logger = structlog.get_logger(__name__)

_FIGURE_RE = re.compile(r"(?:Figure|Fig\.?)\s+(\d+[\.\-]?\d*)", re.IGNORECASE)

_PAGE_ADJACENCY = 1


def _normalize_figure_number(raw: str) -> str:
    """Normalise figure numbers so that '1-3' and '1.3' compare equal."""
    return raw.strip().replace("-", ".")


class ImageLinker:
    """Links images to text chunks for a given source document."""

    async def link_images_to_chunks(self, source: str, session: AsyncSession) -> int:
        """Create explicit and contextual links between images and chunks.

        Args:
            source: The source identifier (e.g. "donaldson").
            session: Async SQLAlchemy session.

        Returns:
            Total number of new junction rows inserted.
        """
        explicit_pairs = await self._build_explicit_pairs(source, session)
        contextual_pairs = await self._build_contextual_pairs(source, session, explicit_pairs)

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

        if rows:
            session.add_all(rows)
            await session.flush()

        logger.info(
            "image_linker.linked",
            source=source,
            explicit=len(explicit_pairs),
            contextual=len(contextual_pairs),
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
