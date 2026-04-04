"""Celery task for RAG indexation — processes course PDFs into vector embeddings."""

import os
import time
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")

# Rough per-MB throughput estimates for ETA (seconds)
_SECS_PER_MB_EXTRACT = 2.0
_SECS_PER_MB_CHUNK = 0.5
_SECS_PER_CHUNK_EMBED = 0.05
_SECS_PER_CHUNK_STORE = 0.02


def _estimate_total_seconds(pdf_files: list[Path]) -> float:
    total_mb = sum(f.stat().st_size for f in pdf_files) / (1024 * 1024)
    estimated_chunks = total_mb * 40
    return (
        total_mb * _SECS_PER_MB_EXTRACT
        + total_mb * _SECS_PER_MB_CHUNK
        + estimated_chunks * _SECS_PER_CHUNK_EMBED
        + estimated_chunks * _SECS_PER_CHUNK_STORE
    )


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

    estimated_total = _estimate_total_seconds(pdf_files)
    start_time = time.monotonic()

    def _remaining(progress_fraction: float) -> int:
        elapsed = time.monotonic() - start_time
        if progress_fraction <= 0:
            return int(estimated_total)
        estimated_at_rate = elapsed / progress_fraction
        remaining = max(0, estimated_at_rate - elapsed)
        return int(remaining)

    self.update_state(
        state="EXTRACTING",
        meta={
            "step": "extracting",
            "step_label": "Extracting text from PDFs",
            "progress": 0,
            "files_total": len(pdf_files),
            "files_processed": 0,
            "current_file": pdf_files[0].name if pdf_files else "",
            "chunks_processed": 0,
            "estimated_seconds_remaining": int(estimated_total),
        },
    )

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
            file_progress = i / len(pdf_files)

            self.update_state(
                state="EXTRACTING",
                meta={
                    "step": "extracting",
                    "step_label": f"Extracting PDF {i + 1}/{len(pdf_files)}",
                    "progress": int(file_progress * 25),
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(file_progress * 0.25),
                },
            )

            self.update_state(
                state="CHUNKING",
                meta={
                    "step": "chunking",
                    "step_label": f"Chunking PDF {i + 1}/{len(pdf_files)}",
                    "progress": int(file_progress * 25 + 25),
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(
                        file_progress * 0.25 + 0.25
                    ),
                },
            )

            self.update_state(
                state="EMBEDDING",
                meta={
                    "step": "embedding",
                    "step_label": f"Generating embeddings {i + 1}/{len(pdf_files)}",
                    "progress": int(file_progress * 25 + 50),
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(
                        file_progress * 0.25 + 0.50
                    ),
                },
            )

            chunks = await pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=rag_collection_id,
            )
            total_chunks += chunks

            self.update_state(
                state="STORING",
                meta={
                    "step": "storing",
                    "step_label": f"Storing {total_chunks} chunks",
                    "progress": int((i + 1) / len(pdf_files) * 25 + 75),
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(
                        (i + 1) / len(pdf_files) * 0.25 + 0.75
                    ),
                },
            )

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
            meta={
                "step": "complete",
                "step_label": "Indexation complete",
                "progress": 100,
                "chunks_stored": total_chunks,
                "files_total": len(pdf_files),
                "files_processed": len(pdf_files),
                "chunks_processed": total_chunks,
                "estimated_seconds_remaining": 0,
            },
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
