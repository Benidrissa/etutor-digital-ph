"""Celery tasks for RAG index management."""

import asyncio
import contextlib
from pathlib import Path

import structlog

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

RAG_JOB_KEY_PREFIX = "rag:job:"
RAG_JOB_TTL = 86400 * 7  # 7 days


def _update_job_status(job_id: str, status: str, result: dict | None = None) -> None:
    """Update job status in Redis (sync version for Celery tasks)."""
    import json
    import time

    import redis

    from app.infrastructure.config.settings import settings

    r = redis.from_url(settings.redis_url)
    data = {
        "job_id": job_id,
        "status": status,
        "updated_at": int(time.time()),
    }
    if result:
        data.update(result)
    r.setex(f"{RAG_JOB_KEY_PREFIX}{job_id}", RAG_JOB_TTL, json.dumps(data))


@celery_app.task(
    bind=True,
    name="app.tasks.rag_indexing.reindex_source",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    rate_limit="2/m",
)
def reindex_source(self, source_id: str | None = None, resources_dir: str | None = None) -> dict:
    """Re-index one or all RAG source documents.

    Args:
        source_id: Optional source identifier to re-index selectively.
            If None, re-indexes all sources.
        resources_dir: Optional path to resources directory.

    Returns:
        dict: Task result with chunk counts per source.
    """
    job_id = self.request.id
    logger.info("Starting RAG re-index task", job_id=job_id, source_id=source_id)
    _update_job_status(job_id, "running")

    try:
        result = asyncio.run(_reindex_async(source_id, resources_dir))
        _update_job_status(job_id, "completed", result)
        logger.info("RAG re-index completed", job_id=job_id, result=result)
        return result
    except Exception as exc:
        logger.error("RAG re-index failed", job_id=job_id, error=str(exc))
        _update_job_status(job_id, "failed", {"error": str(exc)})
        raise


async def _reindex_async(source_id: str | None, resources_dir: str | None) -> dict:
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.pipeline import RAGPipeline
    from app.infrastructure.config.settings import settings

    embedding_service = EmbeddingService(api_key=settings.openai_api_key)
    pipeline = RAGPipeline(embedding_service=embedding_service)

    res_dir = Path(resources_dir) if resources_dir else Path("/app/resources")
    if not res_dir.exists():
        res_dir = Path(__file__).parent.parent.parent.parent / "resources"

    if source_id:
        pdf_files = list(res_dir.glob("*.pdf"))
        source_mappings = {
            "donaldson": "donaldson",
            "triola": "triola",
            "scutchfield": "scutchfield",
            "biostatistics": "triola",
            "essential": "donaldson",
            "principles": "scutchfield",
        }

        target_file = None
        for pdf_file in pdf_files:
            name_lower = pdf_file.name.lower()
            for pattern, src in source_mappings.items():
                if pattern in name_lower and src == source_id:
                    target_file = pdf_file
                    break
            if target_file:
                break

        if not target_file:
            return {"error": f"No PDF found for source: {source_id}", "chunks_indexed": 0}

        await pipeline.clear_source_chunks(source_id)
        chunks = await pipeline.process_pdf_document(pdf_path=target_file, source=source_id)
        return {"source": source_id, "chunks_indexed": chunks}
    else:
        results = await pipeline.process_resources_directory(resources_dir=res_dir)
        return {"sources": results, "total_chunks": sum(results.values())}


@celery_app.task(
    bind=True,
    name="app.tasks.rag_indexing.index_uploaded_pdf",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 15},
    rate_limit="5/m",
)
def index_uploaded_pdf(self, file_path: str, source_id: str) -> dict:
    """Index an uploaded PDF file into the RAG pipeline.

    Args:
        file_path: Path to the uploaded PDF file.
        source_id: Source identifier for the document.

    Returns:
        dict: Task result with chunk count.
    """
    job_id = self.request.id
    logger.info("Starting PDF upload indexing", job_id=job_id, source_id=source_id)
    _update_job_status(job_id, "running")

    try:
        result = asyncio.run(_index_pdf_async(file_path, source_id))
        _update_job_status(job_id, "completed", result)
        logger.info("PDF upload indexing completed", job_id=job_id, result=result)
        return result
    except Exception as exc:
        logger.error("PDF upload indexing failed", job_id=job_id, error=str(exc))
        _update_job_status(job_id, "failed", {"error": str(exc)})
        raise
    finally:
        with contextlib.suppress(Exception):
            Path(file_path).unlink(missing_ok=True)


async def _index_pdf_async(file_path: str, source_id: str) -> dict:
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.pipeline import RAGPipeline
    from app.infrastructure.config.settings import settings

    embedding_service = EmbeddingService(api_key=settings.openai_api_key)
    pipeline = RAGPipeline(embedding_service=embedding_service)

    chunks = await pipeline.process_pdf_document(pdf_path=file_path, source=source_id)
    return {"source": source_id, "chunks_indexed": chunks, "file": file_path}
