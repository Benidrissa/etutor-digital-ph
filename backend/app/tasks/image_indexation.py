"""Celery task for re-indexing course PDF images independently from text indexation."""

import os
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")


class ImageIndexTask(Task):
    """Base task for image indexation with error logging."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Image re-indexation completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Image re-indexation failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=ImageIndexTask,
    time_limit=1800,
    soft_time_limit=1500,
)
def reindex_course_images(self, course_id: str, rag_collection_id: str) -> dict:
    """Re-index images for a course independently from text indexation.

    Iterates over PDFs in uploads/course_resources/{course_id}/ and calls
    pipeline.process_pdf_images() for each. Does NOT touch text chunks.
    No OpenAI dependency — only needs MinIO credentials.
    """
    import asyncio

    logger.info(
        "Starting image re-indexation",
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
            "images_stored": 0,
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
            "images_stored": 0,
        }

    self.update_state(
        state="EXTRACTING_IMAGES",
        meta={
            "step": "extracting_images",
            "step_label": "Extraction des illustrations",
            "progress": 5,
            "files_total": len(pdf_files),
            "files_processed": 0,
            "images_processed": 0,
        },
    )

    async def _run_image_pipeline():
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.pipeline import RAGPipeline

        openai_key = os.getenv("OPENAI_API_KEY", "")
        embedding_service = EmbeddingService(api_key=openai_key) if openai_key else None

        if embedding_service:
            pipeline = RAGPipeline(embedding_service)
        else:
            from app.ai.rag.embeddings import EmbeddingService as _ES

            pipeline = RAGPipeline(_ES(api_key=""))

        total_images = 0

        for i, pdf_path in enumerate(pdf_files):
            extract_progress = 5 + int(((i + 0.5) / len(pdf_files)) * 90)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Extraction des illustrations: {pdf_path.name}",
                    "progress": extract_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "images_processed": total_images,
                },
            )

            try:
                image_count = await pipeline.process_pdf_images(
                    pdf_path=str(pdf_path),
                    source=rag_collection_id,
                    rag_collection_id=rag_collection_id,
                )
                total_images += image_count
                logger.info(
                    "PDF images indexed",
                    file=pdf_path.name,
                    images=image_count,
                    course_id=course_id,
                )
            except Exception as img_exc:
                logger.warning(
                    "Image extraction failed for PDF",
                    file=pdf_path.name,
                    course_id=course_id,
                    error=str(img_exc),
                )

            done_progress = 5 + int(((i + 1) / len(pdf_files)) * 90)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Terminé: {pdf_path.name}",
                    "progress": done_progress,
                    "files_total": len(pdf_files),
                    "files_processed": i + 1,
                    "current_file": pdf_path.name,
                    "images_processed": total_images,
                },
            )

        return total_images

    try:
        total_images = asyncio.run(_run_image_pipeline())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": "Re-indexation des images terminée",
                "progress": 100,
                "images_stored": total_images,
                "files_processed": len(pdf_files),
                "files_total": len(pdf_files),
            },
        )

        logger.info(
            "Image re-indexation complete",
            course_id=course_id,
            total_images=total_images,
        )

        return {
            "status": "complete",
            "images_stored": total_images,
            "files_processed": len(pdf_files),
            "rag_collection_id": rag_collection_id,
        }

    except Exception as exc:
        logger.error(
            "Image re-indexation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise
