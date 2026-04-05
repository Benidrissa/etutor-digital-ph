"""Chunk-image linker for the RAG pipeline.

Links SourceImage records to DocumentChunk records via the source_image_chunks
junction table using two strategies:
- Explicit: chunk content contains a "Figure X.Y" reference matching the image
- Contextual: chunk and image share the same page number (proximity-based)
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk

logger = structlog.get_logger(__name__)

_FIGURE_PATTERN = re.compile(r"Figure\s+(\d+\.?\d*)", re.IGNORECASE)


class ImageLinker:
    """Links SourceImage records to DocumentChunk records for a given source."""

    async def link_images_to_chunks(self, source: str, session: AsyncSession) -> int:
        """
        Create explicit and contextual links between images and chunks.

        Args:
            source: Source book identifier (e.g. "donaldson").
            session: Async SQLAlchemy session.

        Returns:
            Total number of new junction rows created.
        """
        existing_pairs = await self._load_existing_pairs(source, session)

        explicit_links, explicit_pairs = await self._build_explicit_links(
            source, session, existing_pairs
        )

        contextual_links = await self._build_contextual_links(
            source, session, existing_pairs | explicit_pairs
        )

        new_rows = explicit_links + contextual_links
        if new_rows:
            session.add_all(new_rows)
            await session.flush()

        logger.info(
            "Image-chunk linking complete",
            source=source,
            explicit=len(explicit_links),
            contextual=len(contextual_links),
            total=len(new_rows),
        )
        return len(new_rows)

    async def clear_links_for_source(self, source: str, session: AsyncSession) -> int:
        """
        Delete all junction rows for a source (for re-indexation).

        Args:
            source: Source book identifier.
            session: Async SQLAlchemy session.

        Returns:
            Number of deleted rows.
        """
        image_ids_result = await session.execute(
            select(SourceImage.id).where(SourceImage.source == source)
        )
        image_ids = [row[0] for row in image_ids_result]

        if not image_ids:
            return 0

        result = await session.execute(
            delete(SourceImageChunk).where(SourceImageChunk.image_id.in_(image_ids))
        )
        deleted = result.rowcount
        await session.flush()

        logger.info("Cleared image-chunk links", source=source, deleted=deleted)
        return deleted

    async def _load_existing_pairs(
        self, source: str, session: AsyncSession
    ) -> set[tuple[str, str]]:
        """Return set of (image_id, chunk_id) string pairs already in the DB."""
        image_ids_result = await session.execute(
            select(SourceImage.id).where(SourceImage.source == source)
        )
        image_ids = [row[0] for row in image_ids_result]

        if not image_ids:
            return set()

        rows_result = await session.execute(
            select(SourceImageChunk.image_id, SourceImageChunk.chunk_id).where(
                SourceImageChunk.image_id.in_(image_ids)
            )
        )
        return {(str(r[0]), str(r[1])) for r in rows_result}

    async def _build_explicit_links(
        self,
        source: str,
        session: AsyncSession,
        existing_pairs: set[tuple[str, str]],
    ) -> tuple[list[SourceImageChunk], set[tuple[str, str]]]:
        """
        Build explicit links where chunk text references a matching figure number.

        Returns:
            Tuple of (new SourceImageChunk objects, set of new (image_id, chunk_id) pairs).
        """
        chunks_result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.source == source)
        )
        chunks = list(chunks_result.scalars())

        new_links: list[SourceImageChunk] = []
        new_pairs: set[tuple[str, str]] = set()

        for chunk in chunks:
            matches = _FIGURE_PATTERN.findall(chunk.content)
            if not matches:
                continue

            for figure_num in set(matches):
                image_result = await session.execute(
                    select(SourceImage).where(
                        SourceImage.source == source,
                        SourceImage.figure_number.ilike(f"%{figure_num}%"),
                    )
                )
                images = list(image_result.scalars())

                for image in images:
                    pair = (str(image.id), str(chunk.id))
                    if pair in existing_pairs or pair in new_pairs:
                        continue
                    new_links.append(
                        SourceImageChunk(
                            image_id=image.id,
                            chunk_id=chunk.id,
                            reference_type="explicit",
                        )
                    )
                    new_pairs.add(pair)

        return new_links, new_pairs

    async def _build_contextual_links(
        self,
        source: str,
        session: AsyncSession,
        skip_pairs: set[tuple[str, str]],
    ) -> list[SourceImageChunk]:
        """
        Build contextual links for images and chunks that share the same page.

        Skips pairs already linked (explicit or pre-existing).

        Returns:
            List of new SourceImageChunk objects.
        """
        images_result = await session.execute(
            select(SourceImage).where(SourceImage.source == source)
        )
        images = list(images_result.scalars())

        new_links: list[SourceImageChunk] = []
        new_pairs: set[tuple[str, str]] = set()

        for image in images:
            if image.page_number is None:
                continue

            chunks_result = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.source == source,
                    DocumentChunk.page == image.page_number,
                )
            )
            chunks = list(chunks_result.scalars())

            for chunk in chunks:
                pair = (str(image.id), str(chunk.id))
                if pair in skip_pairs or pair in new_pairs:
                    continue
                new_links.append(
                    SourceImageChunk(
                        image_id=image.id,
                        chunk_id=chunk.id,
                        reference_type="contextual",
                    )
                )
                new_pairs.add(pair)

        return new_links
