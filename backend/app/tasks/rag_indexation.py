"""Celery task for RAG indexation — processes course PDFs into vector embeddings."""

import os
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")


class RAGTask(Task):
    """Base task for RAG indexation with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("RAG indexation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("RAG indexation failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=RAGTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 60},
    rate_limit="2/h",
    time_limit=1800,  # 30 min hard limit
    soft_time_limit=1500,  # 25 min soft limit
)
def index_course_resources(self, course_id: str, rag_collection_id: str) -> dict:
    """Index uploaded PDFs for a course into pgvector.

    This runs synchronously in a Celery worker. We use asyncio.run()
    to call the async RAG pipeline from the sync Celery context.
    """
    import asyncio

    logger.info(
        "Starting RAG indexation",
        task_id=self.request.id,
        course_id=course_id,
        rag_collection_id=rag_collection_id,
    )

    self.update_state(state="EXTRACTING", meta={"step": "extracting", "progress": 0})

    course_dir = UPLOAD_DIR / course_id
    if not course_dir.exists():
        return {
            "status": "failed",
            "error": f"No resource directory found: {course_dir}",
            "chunks_stored": 0,
        }

    pdf_files = list(course_dir.glob("*.pdf"))
    if not pdf_files:
        return {
            "status": "failed",
            "error": "No PDF files found in course resources",
            "chunks_stored": 0,
        }

    async def _run_pipeline():
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            raise ValueError("OPENAI_API_KEY not set — cannot generate embeddings")

        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.pipeline import RAGPipeline

        embedding_service = EmbeddingService(api_key=openai_key)
        pipeline = RAGPipeline(embedding_service)

        total_chunks = 0
        for i, pdf_path in enumerate(pdf_files):
            self.update_state(
                state="INDEXING",
                meta={
                    "step": "indexing",
                    "progress": int((i / len(pdf_files)) * 100),
                    "current_file": pdf_path.name,
                    "files_processed": i,
                    "files_total": len(pdf_files),
                },
            )

            chunks = await pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=rag_collection_id,
            )
            total_chunks += chunks
            logger.info(
                "PDF indexed",
                file=pdf_path.name,
                chunks=chunks,
                course_id=course_id,
            )

        return total_chunks

    try:
        total_chunks = asyncio.run(_run_pipeline())

        self.update_state(
            state="COMPLETE",
            meta={"step": "complete", "progress": 100, "chunks_stored": total_chunks},
        )

        return {
            "status": "complete",
            "chunks_stored": total_chunks,
            "files_processed": len(pdf_files),
            "rag_collection_id": rag_collection_id,
        }

    except Exception as exc:
        logger.error(
            "RAG indexation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise
