#!/usr/bin/env python3
"""
RAG Pipeline CLI Script

Processes PDF documents into chunks with embeddings and stores them in pgvector.
This script is idempotent and can be re-run safely.

Usage:
    python scripts/rag_pipeline.py --help
    python scripts/rag_pipeline.py process-resources
    python scripts/rag_pipeline.py process-pdf path/to/document.pdf --source=donaldson
    python scripts/rag_pipeline.py verify-search
    python scripts/rag_pipeline.py stats
    python scripts/rag_pipeline.py clear-source donaldson
"""

import asyncio
import sys
from pathlib import Path

import click
import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.pipeline import RAGPipeline
from app.ai.rag.retriever import SemanticRetriever
from app.infrastructure.config.settings import get_settings

# Configure logging
structlog.configure(
    processors=[structlog.dev.ConsoleRenderer(colors=True)],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
)

logger = structlog.get_logger()


async def get_rag_pipeline() -> RAGPipeline:
    """Create RAG pipeline with embedding service."""
    settings = get_settings()

    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")

    embedding_service = EmbeddingService(api_key=settings.openai_api_key)

    # Test embedding service health
    health = await embedding_service.health_check()
    if health["status"] != "healthy":
        raise ValueError(f"Embedding service unhealthy: {health}")

    return RAGPipeline(embedding_service)


@click.group()
def cli():
    """RAG Pipeline Management CLI"""
    pass


@cli.command()
@click.option("--resources-dir", default="resources", help="Path to resources directory")
async def process_resources(resources_dir: str):
    """Process all PDF files in the resources directory."""
    try:
        pipeline = await get_rag_pipeline()

        logger.info("Starting resource processing", resources_dir=resources_dir)

        results = await pipeline.process_resources_directory(resources_dir)

        if not results:
            logger.warning("No files processed")
            return

        # Display results
        total_chunks = sum(results.values())
        logger.info(
            "Processing completed", total_chunks=total_chunks, sources_processed=len(results)
        )

        for source, count in results.items():
            logger.info("Source processed", source=source, chunks=count)

    except Exception as e:
        logger.error("Failed to process resources", error=str(e))
        sys.exit(1)


@cli.command()
@click.argument("pdf_path")
@click.option("--source", required=True, help="Source identifier (e.g., donaldson)")
@click.option("--level", type=int, help="Difficulty level (1-4)")
async def process_pdf(pdf_path: str, source: str, level: int | None):
    """Process a single PDF file."""
    try:
        pipeline = await get_rag_pipeline()

        logger.info("Processing PDF", pdf_path=pdf_path, source=source, level=level)

        chunk_count = await pipeline.process_pdf_document(
            pdf_path=pdf_path, source=source, level=level
        )

        logger.info("PDF processed successfully", chunks=chunk_count)

    except Exception as e:
        logger.error("Failed to process PDF", error=str(e))
        sys.exit(1)


@cli.command()
async def verify_search():
    """Verify that semantic search is working correctly."""
    try:
        settings = get_settings()
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        retriever = SemanticRetriever(embedding_service)

        logger.info("Running search verification tests")

        results = await retriever.verify_search_functionality()

        logger.info("Verification completed", **results)

        if results["status"] == "healthy":
            logger.info("✅ Semantic search is working correctly!")
        elif results["status"] == "degraded":
            logger.warning("⚠️ Semantic search has issues but is partially working")
        else:
            logger.error("❌ Semantic search is not working properly")
            sys.exit(1)

    except Exception as e:
        logger.error("Verification failed", error=str(e))
        sys.exit(1)


@cli.command()
async def stats():
    """Display statistics about the RAG pipeline."""
    try:
        settings = get_settings()
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        pipeline = RAGPipeline(embedding_service)

        logger.info("Gathering pipeline statistics")

        stats = await pipeline.get_pipeline_stats()

        logger.info("Pipeline Statistics", **stats)

        # Display in a nice format
        print("\n📊 RAG Pipeline Statistics")
        print("=" * 40)
        print(f"Total chunks: {stats['total_chunks']}")
        print(f"Total tokens: {stats['total_tokens']:,}")
        print(f"Average tokens per chunk: {stats['avg_tokens_per_chunk']:.1f}")

        print("\n📚 Sources:")
        for source, info in stats["sources"].items():
            print(f"  - {source}: {info['count']} chunks, {info['tokens']:,} tokens")

        print("\n🌐 Languages:")
        for lang, count in stats["languages"].items():
            print(f"  - {lang}: {count} chunks")

    except Exception as e:
        logger.error("Failed to get statistics", error=str(e))
        sys.exit(1)


@cli.command()
@click.argument("source")
@click.confirmation_option(prompt="Are you sure you want to clear all chunks for this source?")
async def clear_source(source: str):
    """Clear all chunks for a specific source."""
    try:
        settings = get_settings()
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        pipeline = RAGPipeline(embedding_service)

        logger.info("Clearing source chunks", source=source)

        deleted_count = await pipeline.clear_source_chunks(source)

        logger.info("Source cleared", source=source, deleted_chunks=deleted_count)

    except Exception as e:
        logger.error("Failed to clear source", error=str(e))
        sys.exit(1)


@cli.command()
@click.argument("query")
@click.option("--top-k", default=5, help="Number of results to return")
@click.option("--source", help="Filter by source")
@click.option("--language", help="Filter by language (fr/en)")
async def search(query: str, top_k: int, source: str | None, language: str | None):
    """Perform a semantic search query."""
    try:
        settings = get_settings()
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        retriever = SemanticRetriever(embedding_service)

        filters = {}
        if source:
            filters["source"] = source
        if language:
            filters["language"] = language

        logger.info("Performing semantic search", query=query, filters=filters)

        results = await retriever.search(
            query=query, top_k=top_k, filters=filters if filters else None
        )

        print(f"\n🔍 Search results for: '{query}'")
        print("=" * 60)

        if not results:
            print("No results found.")
            return

        for i, result in enumerate(results, 1):
            chunk = result.chunk
            print(
                f"\n{i}. {chunk.source} - {chunk.chapter or 'N/A'} (similarity: {result.similarity_score:.3f})"
            )
            print(f"   Language: {chunk.language} | Tokens: {chunk.token_count}")
            print(f"   Preview: {chunk.preview}")

    except Exception as e:
        logger.error("Search failed", error=str(e))
        sys.exit(1)


def sync_run(async_func):
    """Run async function in sync context."""

    def wrapper(*args, **kwargs):
        return asyncio.run(async_func(*args, **kwargs))

    return wrapper


# Make commands async-compatible
for cmd in [process_resources, process_pdf, verify_search, stats, clear_source, search]:
    cmd.callback = sync_run(cmd.callback)


if __name__ == "__main__":
    cli()
