"""RAG pipeline for processing documents into searchable chunks with embeddings."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.chunker import TextChunker, detect_language, extract_text_from_pdf
from app.ai.rag.embeddings import EmbeddingService
from app.domain.models.document_chunk import DocumentChunk
from app.infrastructure.persistence.database import get_session

logger = structlog.get_logger()


class RAGPipeline:
    """Main pipeline for processing documents and populating the vector database."""

    def __init__(
        self, embedding_service: EmbeddingService, chunk_size: int = 512, overlap_size: int = 50
    ):
        self.embedding_service = embedding_service
        self.chunker = TextChunker(chunk_size=chunk_size, overlap_size=overlap_size)

    async def process_pdf_document(
        self,
        pdf_path: str | Path,
        source: str,
        level: int | None = None,
        session: AsyncSession | None = None,
    ) -> int:
        """
        Process a single PDF document through the complete RAG pipeline.

        Args:
            pdf_path: Path to the PDF file
            source: Source identifier (e.g., "donaldson", "triola")
            level: Optional difficulty level (1-4)
            session: Database session (will create one if not provided)

        Returns:
            Number of chunks processed
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        logger.info("Starting PDF processing", pdf_path=str(pdf_path), source=source)

        # Extract text from PDF
        try:
            text = extract_text_from_pdf(str(pdf_path))
        except Exception as e:
            logger.error("Failed to extract text from PDF", pdf_path=str(pdf_path), error=str(e))
            raise

        if not text.strip():
            logger.warning("No text extracted from PDF", pdf_path=str(pdf_path))
            return 0

        # Detect language
        language = detect_language(text)
        logger.info("Detected language", language=language, text_length=len(text))

        # Create chunks
        chunks = list(
            self.chunker.chunk_document(text=text, source=source, level=level, language=language)
        )

        if not chunks:
            logger.warning("No chunks created from document", pdf_path=str(pdf_path))
            return 0

        logger.info("Created chunks", chunk_count=len(chunks))

        # Generate embeddings
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = await self.embedding_service.generate_embeddings_batch(chunk_texts)

        # Store in database
        session_provided = session is not None
        if not session_provided:
            async with get_session() as session:
                return await self._store_chunks(chunks, embeddings, session)
        else:
            return await self._store_chunks(chunks, embeddings, session)

    async def _store_chunks(
        self,
        chunks: list[Any],  # DocumentChunk from chunker
        embeddings: list[list[float]],
        session: AsyncSession,
    ) -> int:
        """Store chunks and embeddings in the database."""
        if len(chunks) != len(embeddings):
            raise ValueError("Mismatch between chunks and embeddings count")

        stored_count = 0

        for chunk_data, embedding in zip(chunks, embeddings, strict=False):
            # Check if this chunk already exists (idempotent)
            existing = await session.execute(
                select(DocumentChunk).where(
                    DocumentChunk.source == chunk_data.source,
                    DocumentChunk.chunk_index == chunk_data.chunk_index,
                    DocumentChunk.content == chunk_data.content,
                )
            )

            if existing.scalar_one_or_none():
                logger.debug(
                    "Chunk already exists, skipping",
                    source=chunk_data.source,
                    chunk_index=chunk_data.chunk_index,
                )
                continue

            # Create database model
            db_chunk = DocumentChunk(
                id=uuid4(),
                content=chunk_data.content,
                embedding=embedding,
                source=chunk_data.source,
                chapter=chunk_data.chapter,
                page=chunk_data.page,
                level=chunk_data.level,
                language=chunk_data.language,
                token_count=chunk_data.token_count,
                chunk_index=chunk_data.chunk_index,
            )

            session.add(db_chunk)
            stored_count += 1

        await session.commit()
        logger.info("Stored chunks in database", stored_count=stored_count)

        return stored_count

    async def process_resources_directory(
        self, resources_dir: str | Path, source_mappings: dict[str, str] | None = None
    ) -> dict[str, int]:
        """
        Process all PDF files in the resources directory.

        Args:
            resources_dir: Path to directory containing PDF files
            source_mappings: Optional mapping of filename patterns to source names

        Returns:
            Dictionary mapping source names to chunk counts
        """
        resources_dir = Path(resources_dir)

        if not resources_dir.exists():
            raise FileNotFoundError(f"Resources directory not found: {resources_dir}")

        # Default source mappings based on filename patterns
        if source_mappings is None:
            source_mappings = {
                "donaldson": "donaldson",
                "triola": "triola",
                "scutchfield": "scutchfield",
                "biostatistics": "triola",  # Alternative pattern
                "essential": "donaldson",  # Alternative pattern
                "principles": "scutchfield",  # Alternative pattern
            }

        results = {}
        pdf_files = list(resources_dir.glob("*.pdf"))

        if not pdf_files:
            logger.warning(
                "No PDF files found in resources directory", directory=str(resources_dir)
            )
            return results

        logger.info("Found PDF files", count=len(pdf_files), directory=str(resources_dir))

        for pdf_file in pdf_files:
            # Determine source name from filename
            source = self._determine_source_name(pdf_file.name, source_mappings)

            try:
                chunk_count = await self.process_pdf_document(pdf_path=pdf_file, source=source)
                results[source] = chunk_count
                logger.info(
                    "Processed PDF successfully",
                    file=pdf_file.name,
                    source=source,
                    chunks=chunk_count,
                )
            except Exception as e:
                logger.error(
                    "Failed to process PDF", file=pdf_file.name, source=source, error=str(e)
                )
                results[source] = 0

        return results

    def _determine_source_name(self, filename: str, source_mappings: dict[str, str]) -> str:
        """Determine source name from filename using pattern matching."""
        filename_lower = filename.lower()

        for pattern, source in source_mappings.items():
            if pattern.lower() in filename_lower:
                return source

        # Fallback: use filename without extension
        return filename.rsplit(".", 1)[0].lower().replace(" ", "_")

    async def clear_source_chunks(self, source: str, session: AsyncSession | None = None) -> int:
        """
        Remove all chunks for a specific source (useful for reprocessing).

        Args:
            source: Source identifier to clear
            session: Database session

        Returns:
            Number of chunks removed
        """
        session_provided = session is not None
        if not session_provided:
            async with get_session() as session:
                return await self._clear_chunks(source, session)
        else:
            return await self._clear_chunks(source, session)

    async def _clear_chunks(self, source: str, session: AsyncSession) -> int:
        """Clear chunks from database."""
        # Count existing chunks
        count_result = await session.execute(
            select(DocumentChunk).where(DocumentChunk.source == source)
        )
        existing_count = len(count_result.scalars().all())

        if existing_count == 0:
            logger.info("No existing chunks found for source", source=source)
            return 0

        # Delete chunks
        await session.execute(delete(DocumentChunk).where(DocumentChunk.source == source))
        await session.commit()

        logger.info("Cleared existing chunks", source=source, count=existing_count)
        return existing_count

    async def get_pipeline_stats(self, session: AsyncSession | None = None) -> dict[str, Any]:
        """Get statistics about the current state of the pipeline."""
        session_provided = session is not None
        if not session_provided:
            async with get_session() as session:
                return await self._get_stats(session)
        else:
            return await self._get_stats(session)

    async def _get_stats(self, session: AsyncSession) -> dict[str, Any]:
        """Get pipeline statistics."""
        # Get all chunks
        result = await session.execute(select(DocumentChunk))
        chunks = result.scalars().all()

        if not chunks:
            return {"total_chunks": 0, "sources": {}, "languages": {}, "total_tokens": 0}

        # Calculate stats
        sources = {}
        languages = {}
        total_tokens = 0

        for chunk in chunks:
            # Source stats
            if chunk.source not in sources:
                sources[chunk.source] = {"count": 0, "tokens": 0}
            sources[chunk.source]["count"] += 1
            sources[chunk.source]["tokens"] += chunk.token_count

            # Language stats
            if chunk.language not in languages:
                languages[chunk.language] = 0
            languages[chunk.language] += 1

            total_tokens += chunk.token_count

        return {
            "total_chunks": len(chunks),
            "sources": sources,
            "languages": languages,
            "total_tokens": total_tokens,
            "avg_tokens_per_chunk": total_tokens / len(chunks) if chunks else 0,
        }
