"""Per-course backfill of quiz ``option_misconceptions`` (admin, opt-in).

Quizzes generated before ``option_misconceptions`` existed cannot be checked
for "every wrong option traps a misconception" (the admin MCQ audit reports
them as ``misconceptions_unchecked``). This task regenerates every quiz row of
ONE course, in every language, level and country it was generated for, so the
regenerated rows carry the field.

It deliberately has no generator of its own: each row goes through
``QuizService.get_or_generate_quiz(force_regenerate=True)``, which overwrites
the cached row in place with the current prompts. Around that call it:

* skips manually edited rows (an admin's edit is never overwritten) and, unless
  ``force``, rows whose every question already carries misconceptions — so a
  re-run after a partial failure only redoes what is still missing;
* writes a ``generated_content_revisions`` pre-image (trigger ``mcq_backfill``)
  first, so a regeneration that reads worse can be rolled back;
* marks the row ``quality_status="pending"`` afterwards, because the quality
  agent's score described the old text;
* attributes the AI spend to ``quiz_generation`` with the course and the
  admin who asked, through the usage-ledger context.

Rows are processed one at a time, each in its own session and transaction, so
one failure (or a second, concurrent run) never leaves another row half
written. A Redis lock keyed by course keeps a second click from dispatching a
second run while one is in flight; the task releases it when done.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import Counter
from typing import Any

import structlog

from app.ai.usage_context import set_ai_context
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

#: Long enough for a large course (each quiz takes seconds to tens of seconds).
BACKFILL_SOFT_LIMIT_S = 2 * 60 * 60
BACKFILL_HARD_LIMIT_S = BACKFILL_SOFT_LIMIT_S + 60
#: The dispatch lock outlives the hard limit, so a crashed run cannot block
#: the next one for longer than that.
LOCK_TTL_S = BACKFILL_HARD_LIMIT_S + 60
REVISION_TRIGGER = "mcq_backfill"

OUTCOMES = (
    "regenerated",
    "skipped_manually_edited",
    "skipped_has_misconceptions",
    "skipped_no_country",
    "not_overwritten",
    "missing",
    "failed",
)


def lock_key(course_id: str | uuid.UUID) -> str:
    return f"mcq_backfill:{course_id}"


def _safe_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def has_misconceptions(content: Any) -> bool:
    """True when every question of a stored quiz carries ``option_misconceptions``."""
    if not isinstance(content, dict):
        return False
    questions = content.get("questions")
    if not isinstance(questions, list) or not questions:
        return False
    return all(
        isinstance(q, dict) and isinstance(q.get("option_misconceptions"), list) for q in questions
    )


async def regenerate_quiz_row(
    session: Any,
    quiz_service: Any,
    content_id: uuid.UUID,
    *,
    force: bool = False,
    triggered_by_user_id: uuid.UUID | None = None,
) -> str:
    """Regenerate one stored quiz row in place; return its outcome (see ``OUTCOMES``)."""
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent
    from app.domain.models.course_quality import GeneratedContentRevision
    from app.domain.models.module_unit import ModuleUnit

    gc = await session.get(GeneratedContent, content_id)
    if gc is None or gc.content_type != "quiz":
        return "missing"
    if gc.is_manually_edited:
        return "skipped_manually_edited"
    if not force and has_misconceptions(gc.content):
        return "skipped_has_misconceptions"
    if not gc.country_context:
        # The generator keys and prompts on a country; a legacy row without one
        # cannot be regenerated onto itself.
        return "skipped_no_country"

    content = gc.content if isinstance(gc.content, dict) else {}
    unit = await session.get(ModuleUnit, gc.module_unit_id) if gc.module_unit_id else None
    unit_id = unit.unit_number if unit is not None else content.get("unit_id")
    if not unit_id:
        logger.warning("mcq_backfill.no_unit_id", content_id=str(content_id))
        return "failed"
    questions = content.get("questions")
    num_questions = len(questions) if isinstance(questions, list) and questions else None

    # Pre-image first, so the overwrite can be rolled back. One per
    # (row, revision): skip if the quality loop already wrote this one.
    revision = gc.content_revision or 1
    already = await session.execute(
        select(GeneratedContentRevision.id).where(
            GeneratedContentRevision.generated_content_id == gc.id,
            GeneratedContentRevision.revision == revision,
        )
    )
    if already.scalars().first() is None:
        session.add(
            GeneratedContentRevision(
                generated_content_id=gc.id,
                revision=revision,
                content=gc.content,
                sources_cited=gc.sources_cited,
                quality_score_before=gc.quality_score,
                quality_flags_before=gc.quality_flags,
                trigger=REVISION_TRIGGER,
                triggered_by_user_id=triggered_by_user_id,
            )
        )

    # The existing regeneration path; it commits the overwrite (and the
    # pending pre-image with it).
    await quiz_service.get_or_generate_quiz(
        module_id=gc.module_id,
        unit_id=unit_id,
        language=gc.language,
        country=gc.country_context,
        level=gc.level,
        num_questions=num_questions,
        session=session,
        force_regenerate=True,
    )

    await session.refresh(gc)
    if (gc.content_revision or 1) == revision:
        # The generator wrote somewhere else (e.g. a legacy row keyed by the
        # unit_id string while the unit now resolves to a module_unit FK).
        logger.warning("mcq_backfill.not_overwritten", content_id=str(content_id))
        return "not_overwritten"
    gc.quality_status = "pending"
    await session.commit()
    return "regenerated"


async def run_backfill(
    course_id: uuid.UUID,
    *,
    session_factory: Any,
    quiz_service: Any,
    force: bool = False,
    triggered_by_user_id: uuid.UUID | None = None,
    on_progress: Any = None,
) -> dict:
    """Regenerate every quiz row of one course, one row per transaction."""
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module

    async with session_factory() as session:
        result = await session.execute(
            select(GeneratedContent.id)
            .join(Module, Module.id == GeneratedContent.module_id)
            .where(Module.course_id == course_id, GeneratedContent.content_type == "quiz")
            .order_by(Module.module_number, GeneratedContent.language, GeneratedContent.id)
        )
        content_ids = list(result.scalars().all())

    counts: Counter[str] = Counter({outcome: 0 for outcome in OUTCOMES})
    failures: list[dict] = []
    for index, content_id in enumerate(content_ids, start=1):
        async with session_factory() as session:
            try:
                outcome = await regenerate_quiz_row(
                    session,
                    quiz_service,
                    content_id,
                    force=force,
                    triggered_by_user_id=triggered_by_user_id,
                )
            except Exception as exc:  # one bad row must not stop the course
                await session.rollback()
                outcome = "failed"
                failures.append({"content_id": str(content_id), "error": str(exc)[:300]})
                logger.warning(
                    "mcq_backfill.row_failed", content_id=str(content_id), error=str(exc)
                )
        counts[outcome] += 1
        if on_progress is not None:
            on_progress({"done": index, "total": len(content_ids), **counts})

    return {
        "status": "complete",
        "course_id": str(course_id),
        "total": len(content_ids),
        **counts,
        "failures": failures[:20],
    }


def _release_lock(course_id: str, task_id: str | None) -> None:
    """Drop the dispatch lock if it is still ours.

    A short-lived synchronous client: the shared ``redis.asyncio`` client binds
    its connections to the event loop that first used them, and this task runs
    a fresh loop per invocation.
    """
    import redis

    from app.infrastructure.config.settings import settings

    try:
        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            key = lock_key(course_id)
            if client.get(key) == task_id:
                client.delete(key)
        finally:
            client.close()
    except Exception as exc:
        logger.warning("mcq_backfill.lock_release_failed", course_id=course_id, error=str(exc))


@celery_app.task(
    bind=True,
    soft_time_limit=BACKFILL_SOFT_LIMIT_S,
    time_limit=BACKFILL_HARD_LIMIT_S,
    acks_late=False,
)
def backfill_course_quiz_misconceptions(
    self,
    course_id: str,
    triggered_by_user_id: str | None = None,
    force: bool = False,
) -> dict:
    """Regenerate one course's quizzes so they carry ``option_misconceptions``.

    ``acks_late`` is off: a redelivered message after a worker crash would
    silently start a second, overlapping bulk regeneration.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.quiz_service import QuizService
    from app.infrastructure.config.settings import settings

    task_id = self.request.id

    def progress(meta: dict) -> None:
        with contextlib.suppress(Exception):  # progress is best-effort
            self.update_state(state="PROGRESS", meta=meta)

    async def _run() -> dict:
        set_ai_context(
            "quiz_generation",
            user_id=_safe_uuid(triggered_by_user_id),
            course_id=_safe_uuid(course_id),
        )
        engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=1)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            embedding_service = EmbeddingService(
                api_key=settings.openai_api_key, model=settings.embedding_model
            )
            service = QuizService(ClaudeService(), SemanticRetriever(embedding_service))
            return await run_backfill(
                uuid.UUID(course_id),
                session_factory=session_factory,
                quiz_service=service,
                force=force,
                triggered_by_user_id=_safe_uuid(triggered_by_user_id),
                on_progress=progress,
            )
        finally:
            await engine.dispose()

    logger.info("mcq_backfill.start", course_id=course_id, force=force, task_id=task_id)
    try:
        result = asyncio.run(_run())
    except Exception as exc:
        logger.error("mcq_backfill.failed", course_id=course_id, error=str(exc), task_id=task_id)
        return {"status": "failed", "course_id": course_id, "error": str(exc)}
    finally:
        _release_lock(course_id, task_id)
    logger.info("mcq_backfill.done", task_id=task_id, **{k: result[k] for k in OUTCOMES})
    return result
