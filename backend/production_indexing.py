"""Production RAG indexing script for SantePublique AOF.

This script:
1. Runs database migrations
2. Extracts and processes 3 reference PDF textbooks
3. Generates embeddings using OpenAI API
4. Stores document chunks in PostgreSQL for RAG pipeline

Expected results:
- ~2,667 document chunks across 3 textbooks
- ~1.28M tokens total processed
- Ready for lesson/quiz generation endpoints

Usage:
    export OPENAI_API_KEY="sk-..."
    export DATABASE_URL="postgresql+asyncpg://..."
    cd backend && uv run python production_indexing.py
"""

import asyncio
import os
import sys
from pathlib import Path

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.rag.pipeline import RAGPipeline
from app.infrastructure.persistence.database import get_async_session

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


def validate_environment() -> None:
    """Validate required environment variables."""
    required_vars = ["OPENAI_API_KEY", "DATABASE_URL"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        logger.error("Missing required environment variables", missing=missing_vars)
        sys.exit(1)

    logger.info("Environment validation passed")


async def run_migrations() -> None:
    """Run Alembic migrations to ensure DB is up to date."""
    logger.info("Running database migrations...")

    try:
        import subprocess

        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info("Migrations completed successfully", output=result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error("Migration failed", error=e.stderr)
        sys.exit(1)


async def verify_database_connection() -> None:
    """Test database connection and basic schema."""
    logger.info("Verifying database connection...")

    try:
        async_session_generator = get_async_session()
        async with async_session_generator.__anext__() as session:
            # Test connection and check key tables exist
            result = await session.execute(
                text("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN ('modules', 'document_chunks', 'module_units')
                ORDER BY table_name;
                """)
            )
            tables = [row[0] for row in result.fetchall()]

            if len(tables) < 3:
                logger.error("Missing required tables", found=tables)
                sys.exit(1)

            logger.info("Database connection verified", tables=tables)
    except Exception as e:
        logger.error("Database connection failed", error=str(e))
        sys.exit(1)


async def check_existing_chunks(session: AsyncSession) -> int:
    """Check if document chunks already exist."""
    result = await session.execute(text("SELECT COUNT(*) FROM document_chunks;"))
    count = result.scalar() or 0
    logger.info("Existing document chunks found", count=count)
    return count


async def get_pdf_paths() -> list[Path]:
    """Get paths to the 3 reference PDF textbooks."""
    resources_dir = Path(__file__).parent.parent / "resources"

    pdf_files = [
        "Donaldsons' Essential Public Health Fourth Edition-min.pdf",
        (
            "Marc M. Triola, Mario F. Triola, Jason Roy - Biostatistics for "
            "the Biological and Health Sciences (2nd Edition) (2017, Pearson) - "
            "libgen.li_compressed (1).pdf"
        ),
        (
            "Principles of Public Health Practice (Delmar Series in  -  "
            "F_ Douglas Scutchfield, William Keck, C_ William Keck  -  "
            "Delmar series in health services  -  An.pdf"
        ),
    ]

    pdf_paths = []
    for pdf_file in pdf_files:
        pdf_path = resources_dir / pdf_file
        if not pdf_path.exists():
            logger.error("PDF file not found", path=str(pdf_path))
            sys.exit(1)
        pdf_paths.append(pdf_path)

    logger.info("PDF files located", count=len(pdf_paths))
    return pdf_paths


async def index_pdfs(pdf_paths: list[Path]) -> None:
    """Index PDF files using RAG pipeline."""
    logger.info("Starting PDF indexing process...")

    try:
        rag_pipeline = RAGPipeline()

        for i, pdf_path in enumerate(pdf_paths, 1):
            logger.info(
                "Processing PDF",
                file=pdf_path.name,
                progress=f"{i}/{len(pdf_paths)}",
            )

            # Extract and index each PDF
            chunks_added = await rag_pipeline.index_pdf(str(pdf_path))

            logger.info(
                "PDF processed successfully",
                file=pdf_path.name,
                chunks_added=chunks_added,
            )

    except Exception as e:
        logger.error("PDF indexing failed", error=str(e), exc_info=True)
        sys.exit(1)


async def verify_indexing_results(session: AsyncSession) -> None:
    """Verify indexing results and provide summary."""
    logger.info("Verifying indexing results...")

    try:
        # Count total chunks
        result = await session.execute(text("SELECT COUNT(*) FROM document_chunks;"))
        total_chunks = result.scalar() or 0

        # Count chunks by source
        result = await session.execute(
            text("""
            SELECT
                COALESCE(metadata->>'source', 'unknown') as source,
                COUNT(*) as chunk_count,
                AVG(LENGTH(content)) as avg_content_length
            FROM document_chunks
            GROUP BY metadata->>'source'
            ORDER BY chunk_count DESC;
            """)
        )

        sources_stats = result.fetchall()

        logger.info(
            "Indexing verification complete",
            total_chunks=total_chunks,
            sources=len(sources_stats),
        )

        for source, chunk_count, avg_length in sources_stats:
            logger.info(
                "Source statistics",
                source=source,
                chunks=chunk_count,
                avg_length=int(avg_length or 0),
            )

        if total_chunks < 2000:
            logger.warning(
                "Low chunk count detected",
                expected="~2,667",
                actual=total_chunks,
            )

    except Exception as e:
        logger.error("Verification failed", error=str(e))
        sys.exit(1)


async def main() -> None:
    """Main production indexing workflow."""
    logger.info("Starting production RAG indexing", script="production_indexing.py")

    try:
        # Step 1: Validate environment
        validate_environment()

        # Step 2: Run migrations
        await run_migrations()

        # Step 3: Verify database connection
        await verify_database_connection()

        # Step 4: Check existing chunks
        async_session_generator = get_async_session()
        async with async_session_generator.__anext__() as session:
            existing_chunks = await check_existing_chunks(session)

            if existing_chunks > 0:
                logger.warning(
                    "Document chunks already exist",
                    count=existing_chunks,
                    action="will_add_to_existing",
                )

        # Step 5: Get PDF paths
        pdf_paths = await get_pdf_paths()

        # Step 6: Index PDFs
        await index_pdfs(pdf_paths)

        # Step 7: Verify results
        async with async_session_generator.__anext__() as session:
            await verify_indexing_results(session)

        logger.info(
            "Production indexing completed successfully",
            status="success",
            next_steps="Content generation endpoints should now work",
        )

    except KeyboardInterrupt:
        logger.info("Indexing cancelled by user")
        sys.exit(130)
    except Exception as e:
        logger.error("Production indexing failed", error=str(e), exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
