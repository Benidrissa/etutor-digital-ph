"""Links document chunks to source images via explicit and contextual references."""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk

logger = structlog.get_logger(__name__)

_FIGURE_PATTERN = re.compile(r"Figure\s+(\d+\.?\d*)", re.IGNORECASE)


class ImageLinker:
    """Links SourceImage records to DocumentChunk records.

    Two linkage strategies:
    - Explicit: chunk content mentions "Figure X.Y" and a matching SourceImage exists.
    - Contextual: image and chunk share the same page number (same-page proximity).
    """

    async def link_images_to_chunks(self, source: str, session: AsyncSession) -> int:
        """Create junction rows linking images to chunks for the given source.

        Args:
            source: Source identifier (e.g. "donaldson", "triola").
            session: Async SQLAlchemy session.

        Returns:
            Total number of junction rows inserted.
        """
        explicit_pairs: list[tuple[uuid.UUID, uuid.UUID]] = await self._build_explicit_pairs(
            source, session
        )
        explicit_set: set[tuple[uuid.UUID, uuid.UUID]] = set(explicit_pairs)

        contextual_pairs: list[tuple[uuid.UUID, uuid.UUID]] = await self._build_contextual_pairs(
            source, session, skip_pairs=explicit_set
        )

        rows_to_insert: list[dict] = [
            {
                "id": uuid.uuid4(),
                "image_id": img_id,
                "chunk_id": chunk_id,
                "reference_type": "explicit",
            }
            for img_id, chunk_id in explicit_pairs
        ] + [
            {
                "id": uuid.uuid4(),
                "image_id": img_id,
                "chunk_id": chunk_id,
                "reference_type": "contextual",
            }
            for img_id, chunk_id in contextual_pairs
        ]

        if not rows_to_insert:
            logger.info("No image-chunk links to insert", source=source)
            return 0

        stmt = (
            insert(SourceImageChunk)
            .values(rows_to_insert)
            .on_conflict_do_nothing(constraint="uq_source_image_chunk")
        )
        await session.execute(stmt)
        await session.commit()

        total = len(rows_to_insert)
        logger.info(
            "Inserted image-chunk links",
            source=source,
            explicit=len(explicit_pairs),
            contextual=len(contextual_pairs),
            total=total,
        )
        return total

    async def clear_links_for_source(self, source: str, session: AsyncSession) -> int:
        """Delete all junction rows for a given source (for re-indexation).

        Args:
            source: Source identifier.
            session: Async SQLAlchemy session.

        Returns:
            Number of rows deleted.
        """
        image_ids_result = await session.execute(
            select(SourceImage.id).where(SourceImage.source == source)
        )
        image_ids = [row[0] for row in image_ids_result.all()]

        if not image_ids:
            logger.info("No source images found to clear links for", source=source)
            return 0

        result = await session.execute(
            delete(SourceImageChunk).where(SourceImageChunk.image_id.in_(image_ids))
        )
        await session.commit()

        deleted = result.rowcount
        logger.info("Cleared image-chunk links", source=source, deleted=deleted)
        return deleted

    async def _build_explicit_pairs(
        self, source: str, session: AsyncSession
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Find explicit figure-reference pairs by scanning chunk text."""
        chunks_result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.source == source)
        )
        chunks = chunks_result.scalars().all()

        images_result = await session.execute(
            select(SourceImage).where(
                SourceImage.source == source,
                SourceImage.figure_number.isnot(None),
            )
        )
        images = images_result.scalars().all()

        figure_map: dict[str, list[SourceImage]] = {}
        for image in images:
            if image.figure_number:
                normalized = self._normalize_figure_number(image.figure_number)
                figure_map.setdefault(normalized, []).append(image)

        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        pairs: list[tuple[uuid.UUID, uuid.UUID]] = []

        for chunk in chunks:
            matches = _FIGURE_PATTERN.findall(chunk.content)
            for match in matches:
                normalized = match.strip()
                matched_images = figure_map.get(normalized, [])
                for image in matched_images:
                    pair = (image.id, chunk.id)
                    if pair not in seen:
                        seen.add(pair)
                        pairs.append(pair)

        return pairs

    async def _build_contextual_pairs(
        self,
        source: str,
        session: AsyncSession,
        skip_pairs: set[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Find same-page proximity pairs between images and chunks."""
        images_result = await session.execute(
            select(SourceImage).where(SourceImage.source == source)
        )
        images = images_result.scalars().all()

        chunks_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.source == source,
                DocumentChunk.page.isnot(None),
            )
        )
        chunks = chunks_result.scalars().all()

        page_to_chunks: dict[int, list[DocumentChunk]] = {}
        for chunk in chunks:
            if chunk.page is not None:
                page_to_chunks.setdefault(chunk.page, []).append(chunk)

        seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
        pairs: list[tuple[uuid.UUID, uuid.UUID]] = []

        for image in images:
            same_page_chunks = page_to_chunks.get(image.page_number, [])
            for chunk in same_page_chunks:
                pair = (image.id, chunk.id)
                if pair not in skip_pairs and pair not in seen:
                    seen.add(pair)
                    pairs.append(pair)

        return pairs

    @staticmethod
    def _normalize_figure_number(raw: str) -> str:
        """Extract the numeric part from a figure reference string.

        E.g. "Figure 3.1" -> "3.1", "Fig. 2" -> "2".
        """
        m = re.search(r"(\d+\.?\d*)", raw)
        return m.group(1) if m else raw.strip()
