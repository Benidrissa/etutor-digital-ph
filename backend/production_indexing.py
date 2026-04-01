#!/usr/bin/env python3
"""
Production RAG Indexing Script

This script sets up the complete RAG (Retrieval-Augmented Generation) pipeline
for the SantePublique AOF learning platform in production.

It performs the following operations:
1. Runs all pending Alembic database migrations
2. Processes reference textbooks into searchable chunks
3. Generates embeddings using OpenAI text-embedding-3-small
4. Stores chunks and embeddings in PostgreSQL with pgvector

Prerequisites:
- PostgreSQL database with pgvector extension
- OPENAI_API_KEY environment variable
- DATABASE_URL environment variable (postgresql+asyncpg://...)

Usage:
    python production_indexing.py [--clear] [--verify-only]

Arguments:
    --clear      Clear existing chunks before indexing
    --verify-only Only verify the setup without running indexing

Expected output: ~2,500-3,000 chunks across 3 textbooks
Total tokens: ~1.2M-1.5M tokens
"""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Set up structured logging
logging.basicConfig(level=logging.INFO)
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer()],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def verify_environment() -> tuple[str, str]:
    """Verify required environment variables are set."""
    database_url = os.getenv("DATABASE_URL")
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if not database_url:
        logger.error("DATABASE_URL environment variable is required")
        sys.exit(1)

    if not openai_api_key:
        logger.error("OPENAI_API_KEY environment variable is required")
        sys.exit(1)

    logger.info(
        "Environment variables verified",
        db_url_masked=database_url[:20] + "..." if len(database_url) > 20 else database_url,
        openai_key_masked="sk-..." + openai_api_key[-4:],
    )

    return database_url, openai_api_key


async def verify_database_connection(database_url: str) -> None:
    """Verify database connection and pgvector extension."""
    try:
        engine = create_async_engine(database_url)

        async with engine.begin() as conn:
            # Test basic connection
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

            # Check pgvector extension
            result = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            )
            if not result.scalar():
                logger.error("pgvector extension not found in database")
                logger.info("Please run: CREATE EXTENSION vector;")
                sys.exit(1)

            logger.info("Database connection verified with pgvector extension")

        await engine.dispose()

    except Exception as e:
        logger.error("Database connection failed", error=str(e))
        sys.exit(1)


def run_migrations() -> None:
    """Run all pending Alembic migrations."""
    try:
        logger.info("Running database migrations...")

        # Configure Alembic
        alembic_cfg = Config("alembic.ini")

        # Run migrations
        command.upgrade(alembic_cfg, "head")

        logger.info("Database migrations completed successfully")

    except Exception as e:
        logger.error("Migration failed", error=str(e))
        sys.exit(1)


async def verify_tables_exist(database_url: str) -> None:
    """Verify that required tables exist after migration."""
    engine = create_async_engine(database_url)

    required_tables = ["modules", "module_units", "document_chunks", "generated_content"]

    try:
        async with engine.begin() as conn:
            for table in required_tables:
                result = await conn.execute(
                    text(
                        "SELECT EXISTS (SELECT FROM information_schema.tables "
                        "WHERE table_name = :table_name)"
                    ),
                    {"table_name": table},
                )
                exists = result.scalar()
                if not exists:
                    logger.error("Required table missing after migration", table=table)
                    sys.exit(1)

            logger.info("All required tables verified", tables=required_tables)

    except Exception as e:
        logger.error("Table verification failed", error=str(e))
        sys.exit(1)

    finally:
        await engine.dispose()


def load_extracted_data() -> list[dict[str, Any]]:
    """Load pre-extracted PDF data from JSON files."""
    data_dir = Path(__file__).parent / "data" / "extracted"

    books = [
        ("donaldson", "donaldson_chapters.json"),
        ("triola", "triola_chapters.json"),
        ("scutchfield", "scutchfield_chapters.json"),
    ]

    all_chapters = []

    for book_id, filename in books:
        file_path = data_dir / filename

        if not file_path.exists():
            logger.error("Extracted data file not found", file=str(file_path))
            sys.exit(1)

        try:
            with open(file_path, encoding="utf-8") as f:
                book_data = json.load(f)

            chapters = book_data.get("chapters", [])
            logger.info("Loaded extracted chapters", book=book_id, chapters=len(chapters))

            # Add book identifier to each chapter
            for chapter in chapters:
                chapter["source_book"] = book_id

            all_chapters.extend(chapters)

        except Exception as e:
            logger.error("Failed to load extracted data", file=filename, error=str(e))
            sys.exit(1)

    logger.info("Total chapters loaded from all books", total_chapters=len(all_chapters))
    return all_chapters


def create_chunks_from_chapters(chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert extracted chapters into chunks for indexing."""
    chunks = []
    chunk_index = 0

    for chapter in chapters:
        content = chapter.get("content", "").strip()
        if not content:
            continue

        source_book = chapter.get("source_book")
        chapter_number = chapter.get("chapter_number", 0)
        page_start = chapter.get("page_range", {}).get("start", 0)

        # Split long content into smaller chunks (approximately 512 tokens each)
        # Rough estimate: 1 token = 4 characters, so ~2048 characters per chunk
        chunk_size = 2048
        overlap = 200  # 50-token overlap

        for i in range(0, len(content), chunk_size - overlap):
            chunk_content = content[i : i + chunk_size]

            if not chunk_content.strip():
                continue

            # Estimate token count (rough approximation)
            estimated_tokens = len(chunk_content) // 4

            chunk = {
                "content": chunk_content,
                "source": source_book,
                "chapter": chapter_number,
                "page": page_start,
                "level": None,  # Will be determined during content generation
                "language": "en",  # Reference textbooks are in English
                "token_count": estimated_tokens,
                "chunk_index": chunk_index,
            }

            chunks.append(chunk)
            chunk_index += 1

    logger.info("Created chunks from chapters", total_chunks=len(chunks))
    return chunks


async def generate_embeddings_and_store(
    database_url: str,
    openai_api_key: str,
    chunks: list[dict[str, Any]],
    clear_existing: bool = False,
) -> None:
    """Generate embeddings and store chunks in database."""
    from uuid import uuid4

    # Import after environment verification
    sys.path.append(str(Path(__file__).parent))

    from app.ai.rag.embeddings import EmbeddingService
    from app.domain.models.document_chunk import DocumentChunk

    # Initialize embedding service
    embedding_service = EmbeddingService(api_key=openai_api_key, model="text-embedding-3-small")

    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            # Clear existing chunks if requested
            if clear_existing:
                logger.info("Clearing existing document chunks...")
                await conn.execute(text("DELETE FROM document_chunks"))
                logger.info("Existing chunks cleared")

        # Process chunks in batches to manage memory and API limits
        batch_size = 100  # OpenAI embedding API batch limit
        total_chunks = len(chunks)
        processed_count = 0

        async with AsyncSession(engine) as session:
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]

                logger.info(
                    "Processing batch",
                    batch_start=i + 1,
                    batch_end=min(i + batch_size, total_chunks),
                    total=total_chunks,
                )

                # Extract content for embedding generation
                batch_content = [chunk["content"] for chunk in batch]

                try:
                    # Generate embeddings
                    embeddings = await embedding_service.generate_embeddings_batch(batch_content)

                    # Create and store document chunks
                    for chunk_data, embedding in zip(batch, embeddings, strict=False):
                        db_chunk = DocumentChunk(
                            id=uuid4(),
                            content=chunk_data["content"],
                            embedding=embedding,
                            source=chunk_data["source"],
                            chapter=chunk_data["chapter"],
                            page=chunk_data["page"],
                            level=chunk_data["level"],
                            language=chunk_data["language"],
                            token_count=chunk_data["token_count"],
                            chunk_index=chunk_data["chunk_index"],
                        )

                        session.add(db_chunk)

                    # Commit batch
                    await session.commit()
                    processed_count += len(batch)

                    logger.info(
                        "Batch processed successfully",
                        processed=processed_count,
                        total=total_chunks,
                        progress_pct=round(100 * processed_count / total_chunks, 1),
                    )

                except Exception as e:
                    logger.error("Batch processing failed", batch_start=i + 1, error=str(e))
                    await session.rollback()
                    raise

        logger.info("All chunks processed and stored successfully", total_processed=processed_count)

    except Exception as e:
        logger.error("Chunk processing and storage failed", error=str(e))
        sys.exit(1)

    finally:
        await engine.dispose()


async def verify_indexing_results(database_url: str) -> dict[str, Any]:
    """Verify the indexing results and return statistics."""
    engine = create_async_engine(database_url)

    try:
        async with engine.begin() as conn:
            # Count total chunks
            result = await conn.execute(text("SELECT COUNT(*) FROM document_chunks"))
            total_chunks = result.scalar()

            # Count chunks by source
            result = await conn.execute(
                text(
                    "SELECT source, COUNT(*) as count FROM document_chunks "
                    "GROUP BY source ORDER BY source"
                )
            )
            source_counts = {row[0]: row[1] for row in result.fetchall()}

            # Calculate total tokens
            result = await conn.execute(text("SELECT SUM(token_count) FROM document_chunks"))
            total_tokens = result.scalar() or 0

            # Average tokens per chunk
            avg_tokens = total_tokens / total_chunks if total_chunks > 0 else 0

            stats = {
                "total_chunks": total_chunks,
                "source_distribution": source_counts,
                "total_tokens": total_tokens,
                "avg_tokens_per_chunk": round(avg_tokens, 1),
            }

            logger.info("Indexing verification completed", **stats)
            return stats

    except Exception as e:
        logger.error("Verification failed", error=str(e))
        sys.exit(1)

    finally:
        await engine.dispose()


async def main():
    """Main production indexing workflow."""
    import argparse

    parser = argparse.ArgumentParser(description="Production RAG Indexing Script")
    parser.add_argument(
        "--clear", action="store_true", help="Clear existing chunks before indexing"
    )
    parser.add_argument(
        "--verify-only", action="store_true", help="Only verify setup without running indexing"
    )

    args = parser.parse_args()

    logger.info("Starting production RAG indexing setup")

    # Step 1: Verify environment
    database_url, openai_api_key = await verify_environment()

    # Step 2: Verify database connection
    await verify_database_connection(database_url)

    # Step 3: Run migrations
    run_migrations()

    # Step 4: Verify tables exist
    await verify_tables_exist(database_url)

    if args.verify_only:
        logger.info("Verification completed successfully - ready for indexing")
        return

    # Step 5: Load extracted PDF data
    chapters = load_extracted_data()

    # Step 6: Create chunks from chapters
    chunks = create_chunks_from_chapters(chapters)

    # Step 7: Generate embeddings and store in database
    await generate_embeddings_and_store(
        database_url, openai_api_key, chunks, clear_existing=args.clear
    )

    # Step 8: Verify results
    await verify_indexing_results(database_url)

    # Final summary
    logger.info("Production RAG indexing completed successfully")
    logger.info("The content generation endpoints should now work correctly")
    logger.info(
        "Expected API endpoints to test:",
        endpoints=[
            "POST /api/v1/content/generate-lesson",
            "POST /api/v1/content/generate-quiz",
            "POST /api/v1/content/generate-flashcards",
        ],
    )


if __name__ == "__main__":
    asyncio.run(main())
