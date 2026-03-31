#!/usr/bin/env python3
"""
Production RAG Pipeline Indexing Script

This script handles the complete RAG indexing pipeline for production deployment:
1. Runs database migrations to ensure schema is up-to-date
2. Indexes all reference PDFs into document_chunks with embeddings
3. Verifies the indexing was successful
4. Creates a summary report

Usage:
    # With environment variables set:
    export OPENAI_API_KEY="your-openai-key"
    export DATABASE_URL="postgresql+asyncpg://user:pass@host:port/db"
    python production_indexing.py

    # Or with arguments:
    python production_indexing.py --openai-key="sk-..." --db-url="postgresql://..."
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure we can import from app
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.pipeline import RAGPipeline
from app.infrastructure.config.settings import get_settings


def check_environment() -> dict[str, str]:
    """Check that required environment variables are set."""
    settings = get_settings()

    issues = []

    if not settings.openai_api_key or settings.openai_api_key == "":
        issues.append("OPENAI_API_KEY is not set or empty")

    if not settings.database_url:
        issues.append("DATABASE_URL is not set")

    if issues:
        print("❌ Environment Issues:")
        for issue in issues:
            print(f"   - {issue}")
        print("\nPlease set the required environment variables:")
        print("   export OPENAI_API_KEY='sk-...'")
        print("   export DATABASE_URL='postgresql+asyncpg://user:pass@host:port/db'")
        return {}

    print("✅ Environment check passed")
    return {
        "openai_api_key": settings.openai_api_key,
        "database_url": settings.database_url,
    }


async def run_migrations():
    """Run Alembic migrations to ensure database schema is up-to-date."""
    print("🔄 Running database migrations...")

    import subprocess

    try:
        subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        )
        print("✅ Database migrations completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Migration failed: {e}")
        print(f"stdout: {e.stdout}")
        print(f"stderr: {e.stderr}")
        return False
    except FileNotFoundError:
        print("❌ Alembic not found. Install with: pip install alembic")
        return False


async def index_pdfs(openai_api_key: str) -> dict[str, int]:
    """Index all PDF files into the database."""
    print("🔄 Starting PDF indexing...")

    # Initialize services
    embedding_service = EmbeddingService(api_key=openai_api_key)

    # Test embedding service
    health = await embedding_service.health_check()
    if health["status"] != "healthy":
        print(f"❌ Embedding service unhealthy: {health}")
        return {}

    print("✅ Embedding service ready")

    # Initialize RAG pipeline
    pipeline = RAGPipeline(embedding_service)

    # Resources directory
    resources_dir = Path("../resources")
    if not resources_dir.exists():
        print(f"❌ Resources directory not found: {resources_dir}")
        return {}

    print(f"📁 Resources directory: {resources_dir}")

    # Index all PDFs
    try:
        results = await pipeline.process_resources_directory(resources_dir)
        print("✅ PDF indexing completed")
        return results
    except Exception as e:
        print(f"❌ PDF indexing failed: {e}")
        return {}


async def verify_indexing() -> dict[str, any]:
    """Verify that indexing was successful."""
    print("🔍 Verifying indexing results...")

    try:
        settings = get_settings()
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        pipeline = RAGPipeline(embedding_service)

        stats = await pipeline.get_pipeline_stats()
        print("✅ Verification completed")
        return stats
    except Exception as e:
        print(f"❌ Verification failed: {e}")
        return {}


def print_summary(indexing_results: dict[str, int], verification_stats: dict[str, any]):
    """Print a summary report."""
    print("\n" + "=" * 60)
    print("📊 RAG PIPELINE INDEXING REPORT")
    print("=" * 60)

    if not indexing_results:
        print("❌ No PDFs were indexed successfully")
        return

    print(f"📚 PDFs Processed: {len(indexing_results)}")
    total_chunks = sum(indexing_results.values())
    print(f"📄 Total Chunks: {total_chunks:,}")

    for source, count in indexing_results.items():
        print(f"   - {source}: {count:,} chunks")

    if verification_stats:
        print("🔍 Database Verification:")
        print(f"   - Total chunks in DB: {verification_stats.get('total_chunks', 0):,}")
        print(f"   - Total tokens: {verification_stats.get('total_tokens', 0):,}")
        print(f"   - Avg tokens/chunk: {verification_stats.get('avg_tokens_per_chunk', 0):.1f}")

        sources = verification_stats.get("sources", {})
        print(f"   - Sources: {', '.join(sources.keys())}")

        languages = verification_stats.get("languages", {})
        print(f"   - Languages: {', '.join(languages.keys())}")

    print("\n✅ RAG pipeline ready for content generation!")
    print("🚀 Lesson and quiz generation endpoints should now work correctly.")


async def main():
    """Main indexing workflow."""
    parser = argparse.ArgumentParser(description="Production RAG Pipeline Indexing")
    parser.add_argument("--openai-key", help="OpenAI API key")
    parser.add_argument("--db-url", help="Database URL")
    parser.add_argument("--skip-migrations", action="store_true", help="Skip running migrations")

    args = parser.parse_args()

    # Set environment variables from arguments if provided
    if args.openai_key:
        os.environ["OPENAI_API_KEY"] = args.openai_key
    if args.db_url:
        os.environ["DATABASE_URL"] = args.db_url

    print("🚀 Starting Production RAG Pipeline Indexing")
    print("-" * 50)

    # Check environment
    env_vars = check_environment()
    if not env_vars:
        sys.exit(1)

    # Run migrations (unless skipped)
    if not args.skip_migrations:
        migration_success = await run_migrations()
        if not migration_success:
            print("❌ Cannot proceed without successful migrations")
            sys.exit(1)
    else:
        print("⚠️  Skipping migrations as requested")

    # Index PDFs
    indexing_results = await index_pdfs(env_vars["openai_api_key"])
    if not indexing_results:
        print("❌ PDF indexing failed")
        sys.exit(1)

    # Verify results
    verification_stats = await verify_indexing()

    # Print summary
    print_summary(indexing_results, verification_stats)

    print("\n🎉 Production RAG indexing completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
