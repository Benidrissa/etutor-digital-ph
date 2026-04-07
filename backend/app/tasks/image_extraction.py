"""Celery task for parallel image extraction — runs concurrently with syllabus generation."""

import time
from pathlib import Path

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")

_BYTES_PER_SECOND_ESTIMATE = 200_000


def _estimate_seconds(pdf_files: list[Path]) -> int:
    total_bytes = sum(p.stat().st_size for p in pdf_files if p.exists())
    return max(10, int(total_bytes / _BYTES_PER_SECOND_ESTIMATE))


class ImageExtractionTask(Task):
    """Base task for image extraction with progress tracking."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Image extraction completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Image extraction failed", task_id=task_id, exception=str(exc))
        try:
            course_id = args[0] if args else kwargs.get("course_id")
            if course_id:
                from sqlalchemy import create_engine, text
                from sqlalchemy.orm import Session

                from app.infrastructure.config.settings import settings

                engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
                with Session(engine) as session:
                    session.execute(
                        text(
                            "UPDATE courses SET image_extraction_task_id = NULL"
                            " WHERE id = :cid AND image_extraction_task_id IS NOT NULL"
                        ),
                        {"cid": course_id},
                    )
                    session.commit()
                engine.dispose()
        except Exception as reset_exc:
            logger.warning("Failed to reset image_extraction_task_id", error=str(reset_exc))


@celery_app.task(
    bind=True,
    base=ImageExtractionTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 30},
    time_limit=900,
    soft_time_limit=780,
)
def extract_course_images(self, course_id: str, rag_collection_id: str) -> dict:
    """Extract images from course PDFs using PyMuPDF (no external API).

    Runs in parallel with syllabus generation. Stores extracted images in the
    database so RAG indexation can skip the image extraction step.
    """
    import asyncio

    logger.info(
        "Starting image extraction",
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
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": "No PDFs found — skipping image extraction",
                "progress": 100,
                "images_stored": 0,
            },
        )
        return {"status": "complete", "images_stored": 0, "files_processed": 0}

    estimated_seconds = _estimate_seconds(pdf_files)
    start_time = time.monotonic()

    def _remaining(progress_pct: float) -> int:
        elapsed = time.monotonic() - start_time
        if progress_pct > 0:
            total_estimated = elapsed / (progress_pct / 100)
            return max(0, int(total_estimated - elapsed))
        return estimated_seconds

    self.update_state(
        state="EXTRACTING_IMAGES",
        meta={
            "step": "extracting_images",
            "step_label": "Extraction des images des PDFs",
            "progress": 5,
            "files_total": len(pdf_files),
            "files_processed": 0,
            "images_processed": 0,
            "estimated_seconds_remaining": estimated_seconds,
        },
    )

    async def _run_extraction():
        from app.ai.rag.pipeline import RAGPipeline
        from app.ai.rag.embeddings import EmbeddingService
        import os

        openai_key = os.getenv("OPENAI_API_KEY", "")
        embedding_service = EmbeddingService(api_key=openai_key) if openai_key else None

        class _NoEmbeddingService:
            async def generate_embedding(self, text: str) -> list[float] | None:
                return None

            async def generate_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
                return [[] for _ in texts]

        pipeline = RAGPipeline(embedding_service or _NoEmbeddingService())  # type: ignore[arg-type]

        total_images = 0
        for i, pdf_path in enumerate(pdf_files):
            progress = 5 + int(((i) / len(pdf_files)) * 90)
            self.update_state(
                state="EXTRACTING_IMAGES",
                meta={
                    "step": "extracting_images",
                    "step_label": f"Extraction des images: {pdf_path.name}",
                    "progress": progress,
                    "files_total": len(pdf_files),
                    "files_processed": i,
                    "current_file": pdf_path.name,
                    "images_processed": total_images,
                    "estimated_seconds_remaining": _remaining(progress),
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
                    "Images extracted from PDF",
                    file=pdf_path.name,
                    images=image_count,
                    course_id=course_id,
                )
            except Exception as img_exc:
                logger.warning(
                    "Image extraction failed for PDF (non-blocking)",
                    file=pdf_path.name,
                    course_id=course_id,
                    error=str(img_exc),
                )

        return total_images

    try:
        total_images = asyncio.run(_run_extraction())

        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": "Extraction des images terminée",
                "progress": 100,
                "images_stored": total_images,
                "files_processed": len(pdf_files),
                "files_total": len(pdf_files),
                "estimated_seconds_remaining": 0,
            },
        )

        logger.info(
            "Image extraction finished",
            course_id=course_id,
            images_stored=total_images,
            files_processed=len(pdf_files),
        )

        return {
            "status": "complete",
            "images_stored": total_images,
            "files_processed": len(pdf_files),
            "rag_collection_id": rag_collection_id,
        }

    except Exception as exc:
        logger.error(
            "Image extraction failed",
            course_id=course_id,
            error=str(exc),
        )
        raise
