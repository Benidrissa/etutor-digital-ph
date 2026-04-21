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

import structlog
from celery import Task
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.ai.translation import translate_figure_caption
from app.domain.models.source_image import SourceImage
from app.infrastructure.config.settings import settings
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

_DEFAULT_BATCH_SIZE = 50
_COMMIT_EVERY = 10


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
        pending_commit = 0

        for idx, img in enumerate(rows):
            try:
                result = await translate_figure_caption(
                    caption=img.caption or "",
                    image_type=img.image_type,
                    figure_number=img.figure_number,
                )
            except Exception as exc:
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
            pending_commit += 1

            if pending_commit >= _COMMIT_EVERY:
                await session.commit()
                pending_commit = 0

            if (idx + 1) % 10 == 0 or idx + 1 == total:
                task.update_state(
                    state="TRANSLATING",
                    meta={
                        "step": "translating",
                        "total": total,
                        "processed": idx + 1,
                        "translated": translated,
                        "failed": failed,
                    },
                )

        if pending_commit:
            await session.commit()

        return {
            "status": "complete",
            "eligible": total,
            "translated": translated,
            "failed": failed,
        }
