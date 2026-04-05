"""Celery task for RAG indexation — processes course PDFs into vector embeddings."""

import os
import time
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")

_BYTES_PER_SECOND_ESTIMATE = 50_000
_CHUNK_EMBED_SECONDS_ESTIMATE = 0.05


def _estimate_seconds(pdf_files: list[Path]) -> int:
    total_bytes = sum(p.stat().st_size for p in pdf_files if p.exists())
    extraction_s = total_bytes / _BYTES_PER_SECOND_ESTIMATE
    estimated_chunks = total_bytes / 2048
    embedding_s = estimated_chunks * _CHUNK_EMBED_SECONDS_ESTIMATE
    return max(30, int(extraction_s + embedding_s))


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
    time_limit=1800,
    soft_time_limit=1500,
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
        self.update_state(
            state="FAILURE",
            meta={
                "step": "failed",
                "progress": 0,
                "error": f"No resource directory found: {course_dir}",
            },
        )
        return {
            "status": "failed",
            "error": f"No resource directory found: {course_dir}",
            "chunks_stored": 0,
        }

    pdf_files = list(course_dir.glob("*.pdf"))
    if not pdf_files:
        self.update_state(
            state="FAILURE",
            meta={
                "step": "failed",
                "progress": 0,
                "error": "No PDF files found in course resources",
            },
        )
        return {
            "status": "failed",
            "error": "No PDF files found in course resources",
            "chunks_stored": 0,
        }

    estimated_seconds = _estimate_seconds(pdf_files)
    start_time = time.monotonic()

    def _remaining(progress_pct: float) -> int:
        elapsed = time.monotonic() - start_time
        if progress_pct > 0:
            total_estimated = elapsed / (progress_pct / 100)
            return max(0, int(total_estimated - elapsed))
        return estimated_seconds

    self.update_state(
        state="EXTRACTING",
        meta={
            "step": "extracting",
            "step_label": "Extraction du texte des PDFs",
            "progress": 5,
            "files_total": len(pdf_files),
            "files_processed": 0,
            "chunks_processed": 0,
            "estimated_seconds_remaining": estimated_seconds,
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
            extract_progress = 5 + int((i / len(pdf_files)) * 30)
            self.update_state(
                state="EXTRACTING",
                meta={
                    "step": "extracting",
                    "step_label": f"Extraction PDF {i + 1}/{len(pdf_files)}: {pdf_path.name}",
                    "progress": extract_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_progress),
                },
            )

            self.update_state(
                state="CHUNKING",
                meta={
                    "step": "chunking",
                    "step_label": f"Découpage en segments: {pdf_path.name}",
                    "progress": extract_progress + 5,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_progress + 5),
                },
            )

            embed_progress = 35 + int(((i + 0.5) / len(pdf_files)) * 50)
            self.update_state(
                state="EMBEDDING",
                meta={
                    "step": "embedding",
                    "step_label": f"Génération des embeddings: {pdf_path.name}",
                    "progress": embed_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(embed_progress),
                },
            )

            # Use PDF filename (without extension) as readable source for citations
            source_name = pdf_path.stem.replace("_", " ")
            chunks = await pipeline.process_pdf_document(
                pdf_path=str(pdf_path),
                source=source_name,
            )
            total_chunks += chunks

            store_progress = 35 + int(((i + 1) / len(pdf_files)) * 45)
            self.update_state(
                state="STORING",
                meta={
                    "step": "storing",
                    "step_label": f"Stockage de {total_chunks} fragments",
                    "progress": store_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(store_progress),
                },
            )

            extract_img_progress = store_progress + int((1 / len(pdf_files)) * 5)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Extraction des illustrations: {pdf_path.name}",
                    "progress": extract_img_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "estimated_seconds_remaining": _remaining(extract_img_progress),
                },
            )

            from app.infrastructure.persistence.database import async_session_factory

            image_count = 0
            try:
                async with async_session_factory() as img_session:
                    image_count = await pipeline.process_pdf_images(
                        pdf_path=str(pdf_path),
                        source=source_name,
                        rag_collection_id=rag_collection_id,
                        session=img_session,
                        resources_path=pdf_path.parent,
                    )
            except Exception as exc:
                logger.warning(
                    "Image extraction failed for PDF, continuing",
                    file=pdf_path.name,
                    error=str(exc),
                )

            link_progress = extract_img_progress + int((1 / len(pdf_files)) * 5)
            self.update_state(
                state="LINKING_IMAGES",
                meta={
                    "step": "linking_images",
                    "step_label": f"Liaison images-texte: {image_count} liens créés",
                    "progress": link_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "chunks_processed": total_chunks,
                    "images_processed": image_count,
                    "estimated_seconds_remaining": _remaining(link_progress),
                },
            )

            logger.info(
                "PDF indexed",
                file=pdf_path.name,
                chunks=chunks,
                images=image_count,
                course_id=course_id,
            )

        return total_chunks

    try:
        total_chunks = asyncio.run(_run_pipeline())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": "Indexation terminée",
                "progress": 100,
                "chunks_stored": total_chunks,
                "files_processed": len(pdf_files),
                "files_total": len(pdf_files),
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
