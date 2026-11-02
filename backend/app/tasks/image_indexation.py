"""Celery task for re-indexing course PDF images independently from text indexation."""

import asyncio
import time
import uuid
from pathlib import Path

import structlog
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.tasks.celery_app import celery_app
from app.tasks.rag_indexation import connect_kill_finalizer, indexation_deadline

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


# Same budget as index_course_resources: this is the recovery path for a run
# that ran out of time on images, so it needs at least the image time that run
# had (#2659).
@celery_app.task(
    bind=True,
    base=ImageIndexTask,
    time_limit=3600,
    soft_time_limit=3300,
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

    deadline = indexation_deadline(self, time.monotonic())

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

    # Same time-budget guard as index_course_resources (#2659): stop between
    # images before the soft limit, and report which PDFs were cut short.
    pending_images = [p.name for p in pdf_files]
    budget_spent = False

    def _out_of_time() -> bool:
        nonlocal budget_spent
        if deadline is not None and time.monotonic() >= deadline:
            budget_spent = True
        return budget_spent

    def _finish(totals: dict) -> dict:
        report = {
            "partial": bool(pending_images),
            "text_incomplete": [],
            "images_incomplete": list(pending_images),
        }
        files_done = len(pdf_files) - len(pending_images)
        self.update_state(
            state="COMPLETE",
            meta={
                "step": "complete",
                "step_label": (
                    "Re-indexation partielle des images (limite de temps atteinte)"
                    if report["partial"]
                    else "Re-indexation des images terminée"
                ),
                "progress": 100,
                **totals,
                "files_processed": files_done,
                "files_total": len(pdf_files),
                **report,
            },
        )
        return {
            "status": "partial_timeout" if report["partial"] else "complete",
            **totals,
            "files_processed": files_done,
            "rag_collection_id": rag_collection_id,
            **report,
        }

    async def _run_image_pipeline():
        import uuid as _uuid

        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.pipeline import RAGPipeline
        from app.ai.usage_context import set_ai_context
        from app.infrastructure.config.settings import settings

        try:
            set_ai_context("rag_indexing", course_id=_uuid.UUID(course_id))
        except (ValueError, TypeError):
            set_ai_context("rag_indexing")

        # Resolves a tenant-set override (encrypted) or the env fallback.
        openai_key = settings.openai_api_key
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

        # pdf stem → course_resource_id so re-extracted images populate the FK
        # and can serve as donors for future courses (#2580). No hashes are passed
        # into process_pdf_images: this is an explicit re-extract, so it must NOT
        # short-circuit to a cached donor.
        resource_id_by_stem: dict[str, uuid.UUID] = {}
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from app.domain.models.course_resource import CourseResource
        from app.infrastructure.config.settings import settings

        _eng = create_engine(settings.database_url_sync, pool_pre_ping=True)
        try:
            with Session(_eng) as _sess:
                for rid, fname, parent in _sess.execute(
                    select(
                        CourseResource.id,
                        CourseResource.filename,
                        CourseResource.parent_filename,
                    ).where(CourseResource.course_id == uuid.UUID(course_id))
                ).all():
                    for stem in (fname, parent):
                        if stem:
                            resource_id_by_stem.setdefault(stem, rid)
        finally:
            _eng.dispose()

        for i, pdf_path in enumerate(pdf_files):
            if _out_of_time():
                logger.warning(
                    "Image re-indexation time budget exhausted — skipping remaining PDFs",
                    course_id=course_id,
                    skipped=pending_images,
                )
                break

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
                resource_id = resource_id_by_stem.get(pdf_path.stem) or resource_id_by_stem.get(
                    pdf_path.name
                )
                image_count = await pipeline.process_pdf_images(
                    pdf_path=str(pdf_path),
                    source=rag_collection_id,
                    rag_collection_id=rag_collection_id,
                    course_resource_id=resource_id,
                    should_stop=_out_of_time,
                )
                total_images += image_count
                logger.info(
                    "PDF images indexed",
                    file=pdf_path.name,
                    images=image_count,
                    course_id=course_id,
                )
            except SoftTimeLimitExceeded:
                # The backstop must reach the outer handler, not this guard.
                raise
            except Exception as img_exc:
                logger.warning(
                    "Image extraction failed for PDF",
                    file=pdf_path.name,
                    course_id=course_id,
                    error=str(img_exc),
                )
            if not budget_spent:
                pending_images.remove(pdf_path.name)

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

        logger.info(
            "Image re-indexation complete",
            course_id=course_id,
            total_images=total_images,
            images_incomplete=pending_images,
        )

        return _finish({"images_stored": total_images})

    except SoftTimeLimitExceeded:
        # Backstop when a single blocking step overran the deadline margin:
        # images are committed one by one, so keep them and report the gap.
        logger.warning(
            "Image re-indexation hit soft time limit — finalizing partial result",
            task_id=self.request.id,
            course_id=course_id,
            images_incomplete=pending_images,
        )
        return _finish({})

    except Exception as exc:
        logger.error(
            "Image re-indexation failed",
            course_id=course_id,
            error=str(exc),
        )
        raise


connect_kill_finalizer(reindex_course_images)


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
            return {"status": "dry_run", "eligible": total, "preview": _purge_preview(rows)}

        deleted, storage_failed = await _delete_image_rows(session, rows, storage)

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


def _purge_preview(rows: list) -> list[dict]:
    """First 20 rows summarised for a purge dry-run response."""
    return [
        {
            "id": str(img.id),
            "rag_collection_id": img.rag_collection_id,
            "page_number": img.page_number,
            "figure_number": img.figure_number,
            "figure_kind": img.figure_kind,
            "width": img.width,
            "height": img.height,
            "storage_key": img.storage_key,
        }
        for img in rows[:20]
    ]


async def _delete_image_rows(session, rows: list, storage) -> tuple[int, int]:
    """Delete source-image rows + their MinIO objects. Returns (deleted, storage_failed).

    A MinIO failure is logged and counted but never blocks the DB delete — the
    junction rows cascade and any baked-in ``{{source_image:UUID}}`` lesson
    marker becomes a no-op orphan (dropped client-side, #2428).
    """
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
                    "Failed to delete figure object from storage",
                    source_image_id=str(img.id),
                    key=key,
                    error=str(exc),
                )
        await session.delete(img)
        deleted += 1
    await session.commit()
    return deleted, storage_failed


# ---------------------------------------------------------------------------
# Cleanup for mis-extracted body-text crops (#2431)
# ---------------------------------------------------------------------------
#
# The vision classifier (figure_classifier `body_text`) flags source_images
# whose binary is a screenshot of running page text, not a figure. Duplicate
# figure_numbers used to let an explicit "Figure X" citation resolve to one of
# these crops (last-writer-wins in the linker, since fixed). Purge them so they
# never render; lessons that cited a now-deleted image drop the orphan
# {{source_image:UUID}} marker cleanly client-side (#2428). Unlike the
# full-page purge above, this keys purely on the classified kind, so it catches
# captioned, non-full-page crops too. Run `backfill_figure_kinds` first.


class PurgeBodyTextFiguresTask(Task):
    """Celery base for the body-text figure purge."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Body-text figure purge completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Body-text figure purge failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=PurgeBodyTextFiguresTask,
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
    acks_late=False,
)
def purge_body_text_figures(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict:
    """Delete ``source_images`` classified as ``body_text`` (mis-extracted page text).

    Requires ``figure_kind`` to be populated first (run ``backfill_figure_kinds``).
    Args mirror :func:`purge_orphan_full_page_figures`.
    """
    return asyncio.run(
        _run_body_text_purge(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_body_text_purge(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    from app.infrastructure.config.settings import settings
    from app.infrastructure.storage.s3 import S3StorageService

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_body_text_purge_with_factory(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
            storage=S3StorageService(),
        )
    finally:
        await engine.dispose()


async def _run_body_text_purge_with_factory(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
    storage,
) -> dict:
    from app.domain.models.source_image import SourceImage

    async with session_factory() as session:
        stmt = select(SourceImage).where(SourceImage.figure_kind == "body_text")
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Body-text figure purge: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        if dry_run:
            return {"status": "dry_run", "eligible": total, "preview": _purge_preview(rows)}

        deleted, storage_failed = await _delete_image_rows(session, rows, storage)

        logger.info(
            "Body-text figure purge complete",
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


# ---------------------------------------------------------------------------
# Cleanup for unreadable extracted images (#2540)
# ---------------------------------------------------------------------------
#
# ``image_quality.assess_readability`` now drops blank/near-uniform fills,
# random-noise garbage, and undecodable/truncated streams at extraction time.
# Courses indexed before that gate still hold such rows. This purge re-runs the
# exact same check against the *stored* binary (downloaded from MinIO), so the
# verdict matches new ingests, then deletes the unreadable rows. Junction rows
# cascade; any baked-in {{source_image:UUID}} lesson marker becomes a no-op
# orphan, dropped client-side (#2428).
#
# Only the primary raster (``storage_key``) is assessed — the FR variant may be
# an SVG (flowchart/overlay re-derivation), which isn't a decodable raster.
# Unlike the sibling purges this can't be a pure SQL predicate: readability is a
# property of the pixels, so each candidate is downloaded and assessed. ``limit``
# therefore caps the number of rows *scanned* (download + assess), letting the
# job be staged across large libraries within the time limit.


class PurgeUnreadableFiguresTask(Task):
    """Celery base for the unreadable-image purge."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Unreadable-figure purge completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Unreadable-figure purge failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=PurgeUnreadableFiguresTask,
    time_limit=1800,
    soft_time_limit=1500,
    ignore_result=True,
    acks_late=False,
)
def purge_unreadable_figures(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = True,
) -> dict:
    """Delete ``source_images`` whose stored binary is unreadable (#2540).

    Re-runs ``assess_readability`` against the stored raster, matching the
    extraction-time gate. Args mirror :func:`purge_orphan_full_page_figures`,
    except ``limit`` caps the rows *scanned* (each is downloaded + assessed).
    """
    return asyncio.run(
        _run_unreadable_purge(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_unreadable_purge(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    from app.infrastructure.config.settings import settings
    from app.infrastructure.storage.s3 import S3StorageService

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_unreadable_purge_with_factory(
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
            storage=S3StorageService(),
        )
    finally:
        await engine.dispose()


async def _run_unreadable_purge_with_factory(
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
    storage,
) -> dict:
    from app.ai.rag.image_quality import assess_readability
    from app.domain.models.source_image import SourceImage

    async with session_factory() as session:
        stmt = select(SourceImage).where(SourceImage.storage_key.is_not(None))
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        candidates = (await session.execute(stmt)).scalars().all()
        scanned = len(candidates)

        unreadable: list[tuple] = []
        download_failed = 0
        for img in candidates:
            try:
                data = await storage.download_bytes(img.storage_key)
            except Exception as exc:  # noqa: BLE001
                # A transient/missing object isn't proof of unreadable content —
                # skip rather than risk deleting a recoverable row.
                download_failed += 1
                logger.warning(
                    "Unreadable purge: download failed, skipping",
                    source_image_id=str(img.id),
                    key=img.storage_key,
                    error=str(exc),
                )
                continue
            readable, reason = assess_readability(data)
            if not readable:
                unreadable.append((img, reason))

        total = len(unreadable)
        logger.info(
            "Unreadable-figure purge: assessed",
            scanned=scanned,
            unreadable=total,
            download_failed=download_failed,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        if dry_run:
            return {
                "status": "dry_run",
                "scanned": scanned,
                "unreadable": total,
                "download_failed": download_failed,
                "preview": _unreadable_preview(unreadable),
            }

        rows = [img for img, _ in unreadable]
        deleted, storage_failed = await _delete_image_rows(session, rows, storage)

        logger.info(
            "Unreadable-figure purge complete",
            scanned=scanned,
            deleted=deleted,
            storage_failed=storage_failed,
            download_failed=download_failed,
            rag_collection_id=rag_collection_id,
        )
        return {
            "status": "complete",
            "scanned": scanned,
            "unreadable": total,
            "deleted": deleted,
            "storage_failed": storage_failed,
            "download_failed": download_failed,
        }


def _unreadable_preview(pairs: list[tuple]) -> list[dict]:
    """First 20 unreadable rows (with the rejection reason) for a dry-run."""
    return [
        {
            "id": str(img.id),
            "rag_collection_id": img.rag_collection_id,
            "page_number": img.page_number,
            "figure_number": img.figure_number,
            "width": img.width,
            "height": img.height,
            "storage_key": img.storage_key,
            "reason": reason,
        }
        for img, reason in pairs[:20]
    ]
