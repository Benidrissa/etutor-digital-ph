#!/usr/bin/env python3
"""
Production RAG Indexing Script

This script sets up the RAG pipeline for production by:
1. Running database migrations
2. Processing all 3 reference PDFs
3. Generating embeddings and storing in database
4. Verifying search functionality

Usage:
    python production_indexing.py

Environment Variables Required:
    - DATABASE_URL: PostgreSQL connection string with asyncpg driver
    - OPENAI_API_KEY: OpenAI API key for embeddings

Expected Results:
    - ~2,500 document chunks across 3 textbooks
    - ~1.28M tokens total
    - Functional semantic search
"""

import asyncio
import os
import sys
from pathlib import Path

import structlog

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.rag.embeddings import EmbeddingService
from app.ai.rag.pipeline import RAGPipeline
from app.ai.rag.retriever import SemanticRetriever
from app.infrastructure.config.settings import get_settings

# Configure structured logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(colors=True, key_order=["level", "event", "timestamp"])
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def run_migrations():
    """Run Alembic migrations to ensure all tables exist."""
    try:
        import subprocess
        
        logger.info("Running database migrations...")
        
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True
        )
        
        logger.info("Migrations completed successfully", stdout=result.stdout[:200])
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error("Migration failed", error=str(e), stderr=e.stderr[:500])
        return False
    except Exception as e:
        logger.error("Migration error", error=str(e))
        return False


async def setup_rag_pipeline():
    """Initialize and test RAG pipeline components."""
    try:
        settings = get_settings()
        
        # Validate required environment variables
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        if not settings.database_url:
            raise ValueError("DATABASE_URL environment variable is required")
            
        logger.info("Initializing RAG pipeline components...")
        
        # Create embedding service
        embedding_service = EmbeddingService(api_key=settings.openai_api_key)
        
        # Test embedding service health
        health = await embedding_service.health_check()
        if health["status"] != "healthy":
            raise ValueError(f"Embedding service unhealthy: {health}")
        
        logger.info("Embedding service healthy", **health)
        
        # Create RAG pipeline
        pipeline = RAGPipeline(embedding_service)
        
        return pipeline, embedding_service
        
    except Exception as e:
        logger.error("Failed to setup RAG pipeline", error=str(e))
        raise


async def process_reference_pdfs(pipeline: RAGPipeline):
    """Process all 3 reference PDFs into document chunks with embeddings."""
    try:
        # Define resources directory
        resources_dir = Path(__file__).parent.parent / "resources"
        
        if not resources_dir.exists():
            raise FileNotFoundError(f"Resources directory not found: {resources_dir}")
        
        logger.info("Starting PDF processing", resources_dir=str(resources_dir))
        
        # Process all PDFs in resources directory
        results = await pipeline.process_resources_directory(str(resources_dir))
        
        if not results:
            raise ValueError("No PDFs were processed successfully")
        
        # Log results
        total_chunks = sum(results.values())
        total_sources = len(results)
        
        logger.info(
            "PDF processing completed",
            total_chunks=total_chunks,
            total_sources=total_sources,
            results=results
        )
        
        # Expected ranges for validation
        expected_min_chunks = 2000  # Conservative estimate
        expected_max_chunks = 4000  # Liberal estimate
        
        if total_chunks < expected_min_chunks:
            logger.warning(
                "Lower than expected chunk count",
                total_chunks=total_chunks,
                expected_min=expected_min_chunks
            )
        elif total_chunks > expected_max_chunks:
            logger.warning(
                "Higher than expected chunk count", 
                total_chunks=total_chunks,
                expected_max=expected_max_chunks
            )
        else:
            logger.info("Chunk count within expected range", total_chunks=total_chunks)
            
        return results
        
    except Exception as e:
        logger.error("PDF processing failed", error=str(e))
        raise


async def verify_search_functionality(embedding_service: EmbeddingService):
    """Verify that semantic search is working correctly."""
    try:
        logger.info("Verifying search functionality...")
        
        retriever = SemanticRetriever(embedding_service)
        
        # Run verification tests
        verification_results = await retriever.verify_search_functionality()
        
        logger.info("Search verification completed", **verification_results)
        
        # Test with specific health-related queries
        test_queries = [
            "epidemiology public health surveillance",
            "biostatistics data analysis health",
            "health systems financing Africa",
        ]
        
        for query in test_queries:
            try:
                results = await retriever.search(query=query, top_k=3)
                
                logger.info(
                    "Test query successful",
                    query=query,
                    results_count=len(results),
                    top_similarity=results[0].similarity_score if results else 0
                )
                
            except Exception as e:
                logger.error("Test query failed", query=query, error=str(e))
                
        return verification_results["status"] in ["healthy", "degraded"]
        
    except Exception as e:
        logger.error("Search verification failed", error=str(e))
        return False


async def get_final_stats(pipeline: RAGPipeline):
    """Get and display final pipeline statistics."""
    try:
        logger.info("Gathering final pipeline statistics...")
        
        stats = await pipeline.get_pipeline_stats()
        
        # Display comprehensive stats
        logger.info("📊 Final RAG Pipeline Statistics", **stats)
        
        print("\n" + "="*60)
        print("🎯 PRODUCTION RAG INDEXING COMPLETE")
        print("="*60)
        print(f"📚 Total Chunks: {stats['total_chunks']:,}")
        print(f"🔤 Total Tokens: {stats['total_tokens']:,}")
        print(f"📊 Avg Tokens/Chunk: {stats['avg_tokens_per_chunk']:.1f}")
        
        print("\n📖 Sources Processed:")
        for source, info in stats["sources"].items():
            print(f"  • {source}: {info['count']:,} chunks ({info['tokens']:,} tokens)")
            
        print("\n🌍 Languages:")
        for lang, count in stats["languages"].items():
            print(f"  • {lang}: {count:,} chunks")
            
        print("\n✅ Ready for production lesson/quiz generation!")
        print("="*60)
        
        return stats
        
    except Exception as e:
        logger.error("Failed to get final statistics", error=str(e))
        return {}


async def main():
    """Main production indexing workflow."""
    try:
        logger.info("🚀 Starting production RAG indexing...")
        
        # Step 1: Run migrations
        logger.info("Step 1/5: Running database migrations")
        if not await run_migrations():
            logger.error("Migration failed - aborting indexing")
            return False
            
        # Step 2: Setup RAG pipeline
        logger.info("Step 2/5: Setting up RAG pipeline")
        pipeline, embedding_service = await setup_rag_pipeline()
        
        # Step 3: Process PDFs
        logger.info("Step 3/5: Processing reference PDFs")
        pdf_results = await process_reference_pdfs(pipeline)
        
        # Step 4: Verify search
        logger.info("Step 4/5: Verifying search functionality")
        search_ok = await verify_search_functionality(embedding_service)
        
        # Step 5: Final stats
        logger.info("Step 5/5: Gathering final statistics")
        final_stats = await get_final_stats(pipeline)
        
        # Summary
        if search_ok and final_stats.get("total_chunks", 0) > 0:
            logger.info(
                "🎉 Production RAG indexing completed successfully!",
                chunks=final_stats.get("total_chunks", 0),
                sources=len(final_stats.get("sources", {}))
            )
            return True
        else:
            logger.error("❌ Production indexing completed with issues")
            return False
            
    except KeyboardInterrupt:
        logger.warning("Indexing interrupted by user")
        return False
    except Exception as e:
        logger.error("Production indexing failed", error=str(e))
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)