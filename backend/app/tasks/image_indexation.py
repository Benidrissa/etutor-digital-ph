"""Celery task for re-indexing course PDF images independently from text indexation."""

import asyncio
import os
from pathlib import Path

import structlog
from celery import Task
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

UPLOAD_DIR = Path("uploads/course_resources")


class ImageIndexTask(Task):
    """Base task for image-only re-indexation. Clears
    ``courses.indexation_task_id`` on every terminal exit so the
    wizard's polling can never wedge on a stale pointer. Does not
    transition ``creation_step`` — image-only re-index runs at any
    creation_step (typically 'published') and doesn't change it.
    See #2085.
    """

    def on_success(self, retval, task_id, args, kwargs):
        course_id = args[0] if args else kwargs.get("course_id")
        logger.info(
            "Image re-indexation completed",
            task_id=task_id,
            course_id=course_id,
        )
        from app.tasks.rag_indexation import finalize_indexation_state

        finalize_indexation_state(course_id)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        course_id = args[0] if args else kwargs.get("course_id")
        logger.error(
            "Image re-indexation failed",
            task_id=task_id,
            course_id=course_id,
            exception=str(exc),
        )
        from app.tasks.rag_indexation import finalize_indexation_state

        finalize_indexation_state(course_id)


@celery_app.task(
    bind=True,
    base=ImageIndexTask,
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
    acks_late=False,  # Acknowledge immediately to prevent duplicate dispatch
)
def reindex_course_images(
    self, course_id: str, rag_collection_id: str, clear_old: bool = True
) -> dict:
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

        if clear_old:
            self.update_state(
                state="CLEARING_OLD_IMAGES",
                meta={
                    "step": "clearing_old_images",
                    "step_label": "Suppression des anciennes illustrations",
                    "progress": 3,
                    "files_total": len(pdf_files),
                    "files_processed": 0,
                    "images_processed": 0,
                },
            )
            cleared = await pipeline.clear_source_images(source=rag_collection_id)
            logger.info(
                "Cleared old images before re-indexation",
                count=cleared,
                course_id=course_id,
                rag_collection_id=rag_collection_id,
            )

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


# ---------------------------------------------------------------------------
# Cleanup for the body-text "figure" regression (#2272)
# ---------------------------------------------------------------------------
#
# The image_extractor's no-drawings fallback used to rasterize an entire page
# any time the page's text contained "Figure X.Y", even when the match was
# an inline body-text reference. Those rows are now purged here so courses
# indexed before the fix don't keep serving body-text screenshots.
#
# Eligibility is defensive: full-page rasters at 200 DPI for letter-sized
# pages land around 1133×1466, smaller for trimmed scans. Real figures
# rarely both reach >=1000px wide AND >=1300px tall AND have NULL caption
# AND NULL/photo figure_kind. Keep the predicate strict so re-indexing
# isn't required to recover real figures.

_PURGE_MIN_WIDTH = 1000
_PURGE_MIN_HEIGHT = 1300


class PurgeOrphanFiguresTask(Task):
    """Celery base for the orphan full-page figure purge."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Orphan-figure purge completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Orphan-figure purge failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=PurgeOrphanFiguresTask,
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
    acks_late=False,
)
def purge_orphan_full_page_figures(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict:
    """Delete ``source_images`` rows that are full-page body-text rasters.

    Args:
        rag_collection_id: Limit the purge to a single course. None scans
            every collection.
        limit: Maximum rows to delete this invocation. Useful for staged
            rollout against large courses.
        dry_run: When True (default), counts eligible rows and logs a
            preview without touching MinIO or the DB.
    """
    return asyncio.run(
        _run_purge(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_purge(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    from app.infrastructure.config.settings import settings
    from app.infrastructure.storage.s3 import S3StorageService

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_purge_with_factory(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
            storage=S3StorageService(),
        )
    finally:
        await engine.dispose()


async def _run_purge_with_factory(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
    storage,
) -> dict:
    from app.domain.models.source_image import SourceImage

    async with session_factory() as session:
        stmt = select(SourceImage).where(
            SourceImage.caption.is_(None),
            SourceImage.image_type.in_(("photo", "unknown")),
            or_(
                SourceImage.figure_kind.is_(None),
                SourceImage.figure_kind == "photo",
            ),
            and_(
                SourceImage.width.is_not(None),
                SourceImage.width >= _PURGE_MIN_WIDTH,
                SourceImage.height.is_not(None),
                SourceImage.height >= _PURGE_MIN_HEIGHT,
            ),
        )
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Orphan-figure purge: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        if dry_run:
            preview = [
                {
                    "id": str(img.id),
                    "rag_collection_id": img.rag_collection_id,
                    "page_number": img.page_number,
                    "figure_number": img.figure_number,
                    "width": img.width,
                    "height": img.height,
                    "storage_key": img.storage_key,
                }
                for img in rows[:20]
            ]
            return {"status": "dry_run", "eligible": total, "preview": preview}

        deleted = 0
        storage_failed = 0
        for img in rows:
            for key in (img.storage_key, img.storage_key_fr):
                if not key:
                    continue
                try:
                    await storage.delete_object(key)
                except Exception as exc:  # noqa: BLE001
                    storage_failed += 1
                    logger.warning(
                        "Failed to delete orphan-figure object from storage",
                        source_image_id=str(img.id),
                        key=key,
                        error=str(exc),
                    )
            await session.delete(img)
            deleted += 1
        await session.commit()

        logger.info(
            "Orphan-figure purge complete",
            deleted=deleted,
            storage_failed=storage_failed,
            rag_collection_id=rag_collection_id,
        )
        return {
            "status": "complete",
            "eligible": total,
            "deleted": deleted,
            "storage_failed": storage_failed,
        }
