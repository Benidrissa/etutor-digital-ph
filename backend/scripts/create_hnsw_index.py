#!/usr/bin/env python3
"""
Create HNSW index for document chunks embeddings.

This script should be run after documents have been processed and embeddings created.
"""

import asyncio
import sys
from pathlib import Path

import structlog
from sqlalchemy import text

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.infrastructure.persistence.database import get_session

logger = structlog.get_logger()


async def create_hnsw_index():
    """Create HNSW index for fast similarity search."""
    async with get_session() as session:
        try:
            # Check if embeddings exist
            result = await session.execute(
                text("SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL")
            )
            embedding_count = result.scalar()

            if embedding_count == 0:
                logger.error("No embeddings found. Process documents first using rag_pipeline.py")
                return False

            logger.info("Found embeddings, creating HNSW index", count=embedding_count)

            # Drop existing index if it exists
            await session.execute(text("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw"))

            # Create HNSW index
            await session.execute(
                text(
                    "CREATE INDEX idx_document_chunks_embedding_hnsw "
                    "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
                    "WITH (m = 16, ef_construction = 64)"
                )
            )

            await session.commit()
            logger.info("HNSW index created successfully")
            return True

        except Exception as e:
            logger.error("Failed to create HNSW index", error=str(e))
            await session.rollback()
            return False


if __name__ == "__main__":
    success = asyncio.run(create_hnsw_index())
    if not success:
        sys.exit(1)
