"""Image-to-chunk linker for the RAG pipeline.

Links extracted source images to their nearest document chunks by computing
cosine similarity between the image caption embedding and chunk embeddings.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.source_image import SourceImage, SourceImageChunk

logger = structlog.get_logger(__name__)

_TOP_K_CHUNKS = 5
_MIN_SIMILARITY = 0.3


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class ImageLinker:
    """Link source images to document chunks using embedding similarity."""

    async def link_images_to_chunks(self, source: str, session: AsyncSession) -> int:
        """Link all images for a source to their nearest document chunks.

        Args:
            source: Source identifier (e.g. "donaldson").
            session: Async database session.

        Returns:
            Total number of image-chunk links created.
        """
        images_result = await session.execute(
            select(SourceImage).where(SourceImage.source == source)
        )
        images = images_result.scalars().all()

        if not images:
            logger.info("No source images found to link", source=source)
            return 0

        chunks_result = await session.execute(
            select(DocumentChunk).where(
                DocumentChunk.source == source,
                DocumentChunk.embedding.is_not(None),
            )
        )
        chunks = chunks_result.scalars().all()

        if not chunks:
            logger.info("No document chunks with embeddings found", source=source)
            return 0

        total_links = 0

        for image in images:
            if not image.caption_embedding:
                continue

            scored: list[tuple[DocumentChunk, float]] = []
            for chunk in chunks:
                if not chunk.embedding:
                    continue
                sim = _cosine_similarity(image.caption_embedding, chunk.embedding)
                if sim >= _MIN_SIMILARITY:
                    scored.append((chunk, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            top_chunks = scored[:_TOP_K_CHUNKS]

            for chunk, sim in top_chunks:
                existing = await session.execute(
                    select(SourceImageChunk).where(
                        SourceImageChunk.image_id == image.id,
                        SourceImageChunk.chunk_id == chunk.id,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                link = SourceImageChunk(
                    image_id=image.id,
                    chunk_id=chunk.id,
                    similarity_score=sim,
                )
                session.add(link)
                total_links += 1

        await session.commit()
        logger.info(
            "Image-chunk links created",
            source=source,
            images=len(images),
            chunks=len(chunks),
            links=total_links,
        )
        return total_links
