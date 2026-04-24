"""Celery task for backfilling FR/EN translations on existing source_images.

Issue #1820 (epic #1819). Complements ``reindex_course_images`` in
``image_indexation.py``: that task re-runs extraction + linking when PDFs
change; this task fills in the four locale columns (``caption_fr``,
``caption_en``, ``alt_text_fr``, ``alt_text_en``) on rows that predate
Phase 1 of bilingual figure translation.

Idempotent: rows where all four locale columns are already populated are
skipped. Rows whose ``caption`` is NULL or empty are skipped (nothing to
translate). Failures on individual rows are logged and do not abort the
batch — the task keeps going so a transient Claude error doesn't block
the rest of the backfill.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog
from celery import Task
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.ai.translation import (
    classify_figure,
    extract_flowchart_structure,
    extract_label_positions,
    render_overlay_svg,
    render_svg,
    translate_figure_caption,
    translate_labels,
    translate_structure,
)
from app.domain.models.source_image import SourceImage
from app.infrastructure.config.settings import settings
from app.infrastructure.storage.s3 import S3StorageService
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

_DEFAULT_BATCH_SIZE = 50
_COMMIT_EVERY = 10

# Concurrency knobs for the parallel backfill passes (issue #1891).
#   _CONCURRENCY  — max rows processed in parallel per batch. Each row does
#                   up to 3 Claude Haiku calls, so 8 × 3 ≈ 24 concurrent
#                   calls in the worst case. Well under Anthropic's 50 req/s
#                   tier limit; conservative against rate-limit bursts.
#   _BATCH_SIZE   — rows per commit boundary. One `session.commit()` per
#                   batch preserves the crash-safety of the prior sequential
#                   version (at most BATCH_SIZE rows worth of work lost on
#                   process kill) while keeping transactions short.
_CONCURRENCY = 8
_BATCH_SIZE = 40


class ImageTranslationTask(Task):
    """Base task for image translation backfill with error logging."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Image translation backfill completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Image translation backfill failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=ImageTranslationTask,
    time_limit=3600,
    soft_time_limit=3300,
    ignore_result=True,
    acks_late=False,
)
def backfill_image_translations(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Translate captions + alt text for ``source_images`` rows missing them.

    Args:
        rag_collection_id: Limit backfill to a single course's RAG collection.
            None processes every eligible row across all courses.
        limit: Maximum number of rows to process in this invocation. Useful
            for dry-runs and incremental rollout. None = no limit.
        dry_run: If True, count eligible rows and log a preview but do not
            call Claude or write to the DB.
    """
    return asyncio.run(
        _run_backfill(
            task=self,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_backfill(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    # The module-level engine in app.infrastructure.persistence.database is
    # bound to whichever event loop first touches it. Celery wraps this task
    # in asyncio.run(), which creates a fresh loop per invocation — the second
    # call finds pooled connections attached to the first (now-closed) loop
    # and raises "attached to a different loop" (#1827). Own the engine for
    # the task's lifetime and dispose on exit.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_backfill_with_factory(
            task=task,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
        )
    finally:
        await engine.dispose()


async def _run_backfill_with_factory(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    async with session_factory() as session:
        stmt = select(SourceImage).where(
            SourceImage.caption.is_not(None),
            func.length(func.trim(SourceImage.caption)) > 0,
            or_(
                SourceImage.caption_fr.is_(None),
                SourceImage.caption_en.is_(None),
                SourceImage.alt_text_fr.is_(None),
                SourceImage.alt_text_en.is_(None),
            ),
        )
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Image translation backfill: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        task.update_state(
            state="TRANSLATING",
            meta={
                "step": "translating",
                "total": total,
                "processed": 0,
                "translated": 0,
                "failed": 0,
            },
        )

        if dry_run or total == 0:
            return {
                "status": "dry_run" if dry_run else "noop",
                "eligible": total,
                "translated": 0,
                "failed": 0,
            }

        translated = 0
        failed = 0
        sem = asyncio.Semaphore(_CONCURRENCY)

        async def _translate_one(img):
            async with sem:
                try:
                    result = await translate_figure_caption(
                        caption=img.caption or "",
                        image_type=img.image_type,
                        figure_number=img.figure_number,
                    )
                    return img, result, None
                except Exception as exc:  # noqa: BLE001 — log and continue
                    return img, None, exc

        processed = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            batch = rows[batch_start : batch_start + _BATCH_SIZE]
            outcomes = await asyncio.gather(*(_translate_one(img) for img in batch))
            for img, result, exc in outcomes:
                if exc is not None:
                    failed += 1
                    logger.warning(
                        "Translation failed for source image, skipping",
                        source_image_id=str(img.id),
                        figure_number=img.figure_number,
                        error=str(exc),
                    )
                    continue
                img.caption_fr = result.caption_fr
                img.caption_en = result.caption_en
                img.alt_text_fr = result.alt_text_fr
                img.alt_text_en = result.alt_text_en
                session.add(img)
                translated += 1
            await session.commit()
            processed = batch_start + len(batch)
            task.update_state(
                state="TRANSLATING",
                meta={
                    "step": "translating",
                    "total": total,
                    "processed": processed,
                    "translated": translated,
                    "failed": failed,
                },
            )

        return {
            "status": "complete",
            "eligible": total,
            "translated": translated,
            "failed": failed,
        }


# ---------------------------------------------------------------------------
# Phase 2 slice 2 (#1844) — figure-kind classifier backfill
# ---------------------------------------------------------------------------


class FigureClassificationTask(Task):
    """Celery base for the figure-kind classifier backfill."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Figure-kind backfill completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Figure-kind backfill failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=FigureClassificationTask,
    time_limit=3600,
    soft_time_limit=3300,
    ignore_result=True,
    acks_late=False,
)
def backfill_figure_kinds(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Classify ``source_images`` rows that have no ``figure_kind`` yet.

    Args:
        rag_collection_id: Limit backfill to a single course's RAG collection.
            None processes every eligible row across all courses.
        limit: Maximum number of rows to process in this invocation.
        dry_run: If True, count eligible rows and log a preview but do not
            call Claude or write to the DB.
    """
    return asyncio.run(
        _run_kind_backfill(
            task=self,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_kind_backfill(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    # Same task-scoped engine pattern as _run_backfill — each asyncio.run()
    # invocation gets its own pool bound to its own loop (#1827).
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_kind_backfill_with_factory(
            task=task,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
        )
    finally:
        await engine.dispose()


async def _run_kind_backfill_with_factory(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
) -> dict:
    async with session_factory() as session:
        stmt = select(SourceImage).where(
            SourceImage.figure_kind.is_(None),
            SourceImage.storage_url.is_not(None),
        )
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Figure-kind backfill: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        task.update_state(
            state="CLASSIFYING",
            meta={
                "step": "classifying",
                "total": total,
                "processed": 0,
                "classified": 0,
                "failed": 0,
            },
        )

        if dry_run or total == 0:
            return {
                "status": "dry_run" if dry_run else "noop",
                "eligible": total,
                "classified": 0,
                "failed": 0,
            }

        classified = 0
        failed = 0
        sem = asyncio.Semaphore(_CONCURRENCY)

        async with httpx.AsyncClient(timeout=30.0) as http:

            async def _classify_one(img):
                async with sem:
                    try:
                        upstream = await http.get(img.storage_url)
                        upstream.raise_for_status()
                        image_bytes = upstream.content
                    except Exception as exc:  # noqa: BLE001
                        return img, None, ("fetch", exc)
                    try:
                        classification = await classify_figure(image_bytes=image_bytes)
                        return img, classification, None
                    except Exception as exc:  # noqa: BLE001
                        return img, None, ("classify", exc)

            processed = 0
            for batch_start in range(0, total, _BATCH_SIZE):
                batch = rows[batch_start : batch_start + _BATCH_SIZE]
                outcomes = await asyncio.gather(*(_classify_one(img) for img in batch))
                for img, classification, err in outcomes:
                    if err is not None:
                        stage, exc = err
                        failed += 1
                        logger.warning(
                            "Classification %s failed for source image, skipping",
                            stage,
                            source_image_id=str(img.id),
                            figure_number=img.figure_number,
                            error=str(exc),
                        )
                        continue
                    img.figure_kind = classification.kind
                    session.add(img)
                    classified += 1
                await session.commit()
                processed = batch_start + len(batch)
                task.update_state(
                    state="CLASSIFYING",
                    meta={
                        "step": "classifying",
                        "total": total,
                        "processed": processed,
                        "classified": classified,
                        "failed": failed,
                    },
                )

        return {
            "status": "complete",
            "eligible": total,
            "classified": classified,
            "failed": failed,
        }


# ---------------------------------------------------------------------------
# Phase 2 slice 3 (#1852) — clean_flowchart SVG re-derivation backfill
# ---------------------------------------------------------------------------


class FlowchartSvgTask(Task):
    """Celery base for the clean_flowchart SVG re-derivation backfill."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Flowchart SVG backfill completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Flowchart SVG backfill failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=FlowchartSvgTask,
    time_limit=3600,
    soft_time_limit=3300,
    ignore_result=True,
    acks_late=False,
)
def backfill_clean_flowchart_svgs(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Re-derive French SVGs for rows with ``figure_kind = 'clean_flowchart'``.

    Eligible: ``figure_kind = 'clean_flowchart' AND storage_key_fr IS NULL AND
    storage_url IS NOT NULL``. Fetches the English raster from MinIO,
    extracts structure, translates, renders SVG, uploads, writes back
    ``storage_key_fr`` + ``storage_url_fr``.
    """
    return asyncio.run(
        _run_svg_backfill(
            task=self,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_svg_backfill(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_svg_backfill_with_factory(
            task=task,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
            storage=S3StorageService(),
        )
    finally:
        await engine.dispose()


async def _run_svg_backfill_with_factory(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
    storage: S3StorageService,
) -> dict:
    async with session_factory() as session:
        stmt = select(SourceImage).where(
            SourceImage.figure_kind == "clean_flowchart",
            SourceImage.storage_key_fr.is_(None),
            SourceImage.storage_url.is_not(None),
        )
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Flowchart SVG backfill: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        task.update_state(
            state="REDERIVING",
            meta={
                "step": "rederiving",
                "total": total,
                "processed": 0,
                "rendered": 0,
                "failed": 0,
            },
        )

        if dry_run or total == 0:
            return {
                "status": "dry_run" if dry_run else "noop",
                "eligible": total,
                "rendered": 0,
                "failed": 0,
            }

        rendered = 0
        failed = 0
        sem = asyncio.Semaphore(_CONCURRENCY)

        async with httpx.AsyncClient(timeout=30.0) as http:

            async def _rederive_one(img):
                async with sem:
                    try:
                        upstream = await http.get(img.storage_url)
                        upstream.raise_for_status()
                        image_bytes = upstream.content
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("fetch", exc)
                    try:
                        structure = await extract_flowchart_structure(image_bytes=image_bytes)
                        translated = await translate_structure(structure, target_lang="fr")
                        svg_bytes = render_svg(translated)
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("rederive", exc)
                    try:
                        key = _svg_key_for(img)
                        url = await storage.upload_bytes(
                            key=key,
                            data=svg_bytes,
                            content_type="image/svg+xml",
                        )
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("upload", exc)
                    return img, key, url, None

            processed = 0
            for batch_start in range(0, total, _BATCH_SIZE):
                batch = rows[batch_start : batch_start + _BATCH_SIZE]
                outcomes = await asyncio.gather(*(_rederive_one(img) for img in batch))
                for img, key, url, err in outcomes:
                    if err is not None:
                        stage, exc = err
                        failed += 1
                        logger.warning(
                            "SVG %s failed for source image, skipping",
                            stage,
                            source_image_id=str(img.id),
                            figure_number=img.figure_number,
                            error=str(exc),
                        )
                        continue
                    img.storage_key_fr = key
                    img.storage_url_fr = url
                    session.add(img)
                    rendered += 1
                await session.commit()
                processed = batch_start + len(batch)
                task.update_state(
                    state="REDERIVING",
                    meta={
                        "step": "rederiving",
                        "total": total,
                        "processed": processed,
                        "rendered": rendered,
                        "failed": failed,
                    },
                )

        return {
            "status": "complete",
            "eligible": total,
            "rendered": rendered,
            "failed": failed,
        }


def _svg_key_for(img: SourceImage) -> str:
    """Compute a deterministic MinIO key for the French-variant SVG of ``img``.

    Mirrors the English-raster key computed at ingest in
    ``RAGPipeline._process_images`` but with a ``.fr.svg`` suffix so the
    same object path namespace is preserved and the FR variant is
    discoverable next to its English original.
    """
    figure_label = img.figure_number or str(img.id)
    safe_label = figure_label.replace(" ", "_").replace(".", "_")
    prefix = img.rag_collection_id or img.source
    return f"source-images/{prefix}/{img.page_number}_{safe_label}.fr.svg"


# ---------------------------------------------------------------------------
# Phase 2 slice 2.4 (#1883) — complex_diagram raster + numbered-badge overlay
# ---------------------------------------------------------------------------


class ComplexDiagramOverlayTask(Task):
    """Celery base for the complex_diagram overlay backfill."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Complex-diagram overlay backfill completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error("Complex-diagram overlay backfill failed", task_id=task_id, exception=str(exc))


@celery_app.task(
    bind=True,
    base=ComplexDiagramOverlayTask,
    time_limit=3600,
    soft_time_limit=3300,
    ignore_result=True,
    acks_late=False,
)
def backfill_complex_diagram_overlays(
    self,
    rag_collection_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Render French-variant overlays for rows with ``figure_kind = 'complex_diagram'``.

    Eligible: ``figure_kind = 'complex_diagram' AND storage_key_fr IS NULL AND
    storage_url IS NOT NULL``. Fetches the English raster from MinIO,
    extracts label positions, translates them, renders a numbered-badge
    overlay SVG, uploads, writes back ``storage_key_fr`` + ``storage_url_fr``.
    """
    return asyncio.run(
        _run_overlay_backfill(
            task=self,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
        )
    )


async def _run_overlay_backfill(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
) -> dict:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        return await _run_overlay_backfill_with_factory(
            task=task,
            rag_collection_id=rag_collection_id,
            limit=limit,
            dry_run=dry_run,
            session_factory=session_factory,
            storage=S3StorageService(),
        )
    finally:
        await engine.dispose()


async def _run_overlay_backfill_with_factory(
    task: Task,
    rag_collection_id: str | None,
    limit: int | None,
    dry_run: bool,
    session_factory: async_sessionmaker[AsyncSession],
    storage: S3StorageService,
) -> dict:
    async with session_factory() as session:
        stmt = select(SourceImage).where(
            SourceImage.figure_kind == "complex_diagram",
            SourceImage.storage_key_fr.is_(None),
            SourceImage.storage_url.is_not(None),
        )
        if rag_collection_id is not None:
            stmt = stmt.where(SourceImage.rag_collection_id == rag_collection_id)
        if limit is not None:
            stmt = stmt.limit(limit)

        rows = (await session.execute(stmt)).scalars().all()
        total = len(rows)

        logger.info(
            "Complex-diagram overlay backfill: eligible rows",
            total=total,
            rag_collection_id=rag_collection_id,
            dry_run=dry_run,
        )

        task.update_state(
            state="OVERLAYING",
            meta={
                "step": "overlaying",
                "total": total,
                "processed": 0,
                "rendered": 0,
                "failed": 0,
            },
        )

        if dry_run or total == 0:
            return {
                "status": "dry_run" if dry_run else "noop",
                "eligible": total,
                "rendered": 0,
                "failed": 0,
            }

        rendered = 0
        reclassified = 0
        failed = 0
        sem = asyncio.Semaphore(_CONCURRENCY)

        async with httpx.AsyncClient(timeout=30.0) as http:

            async def _overlay_one(img):
                async with sem:
                    try:
                        upstream = await http.get(img.storage_url)
                        upstream.raise_for_status()
                        image_bytes = upstream.content
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("fetch", exc)
                    try:
                        positions = await extract_label_positions(image_bytes=image_bytes)
                        if not positions.labels:
                            # No text found — caller will reclassify as photo
                            # and skip. Avoids an infinite re-process loop
                            # over diagrams Vision can't label.
                            return img, None, None, ("reclassify_photo", None)
                        translated = await translate_labels(positions, target_lang="fr")
                        svg_bytes = render_overlay_svg(
                            image_bytes=image_bytes,
                            width_px=img.width or 1024,
                            height_px=img.height or 768,
                            labels=translated,
                        )
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("render", exc)
                    try:
                        key = _svg_key_for(img)
                        url = await storage.upload_bytes(
                            key=key,
                            data=svg_bytes,
                            content_type="image/svg+xml",
                        )
                    except Exception as exc:  # noqa: BLE001
                        return img, None, None, ("upload", exc)
                    return img, key, url, None

            processed = 0
            for batch_start in range(0, total, _BATCH_SIZE):
                batch = rows[batch_start : batch_start + _BATCH_SIZE]
                outcomes = await asyncio.gather(*(_overlay_one(img) for img in batch))
                for img, key, url, err in outcomes:
                    if err is not None:
                        stage, exc = err
                        if stage == "reclassify_photo":
                            img.figure_kind = "photo"
                            session.add(img)
                            reclassified += 1
                            logger.info(
                                "complex_diagram has no extractable labels; reclassifying as photo",
                                source_image_id=str(img.id),
                                figure_number=img.figure_number,
                            )
                            continue
                        failed += 1
                        logger.warning(
                            "Overlay %s failed for source image, skipping",
                            stage,
                            source_image_id=str(img.id),
                            figure_number=img.figure_number,
                            error=str(exc),
                        )
                        continue
                    img.storage_key_fr = key
                    img.storage_url_fr = url
                    session.add(img)
                    rendered += 1
                await session.commit()
                processed = batch_start + len(batch)
                task.update_state(
                    state="OVERLAYING",
                    meta={
                        "step": "overlaying",
                        "total": total,
                        "processed": processed,
                        "rendered": rendered,
                        "reclassified": reclassified,
                        "failed": failed,
                    },
                )

        return {
            "status": "complete",
            "eligible": total,
            "rendered": rendered,
            "reclassified": reclassified,
            "failed": failed,
        }
