"""Celery tasks for the course quality agent (#2215).

Three roles:

1. **Per-unit auto-trigger** (``assess_unit_task``) — chained via
   ``link=`` from each generator task so every freshly generated unit
   gets a quick score immediately. Cheap path: no glossary build, no
   neighbor digest beyond what the per-unit query produces, no
   regeneration loop. The point is to flag obviously-broken units
   right at generation time.

2. **Course sweep** (``assess_course_task``) — admin-triggered. Builds
   the glossary, then iterates units (with the cached prompt prefix
   reused across every call) running the assess→regenerate loop.
   Bound by ``MAX_REGEN_ATTEMPTS`` and the +3 anti-oscillation guard
   inside the service. Updates the run row at the end with
   ``finalize_run``.

3. **Glossary extraction** (``extract_course_glossary_task``) — runs
   first within a sweep, also exposed standalone for admins who want
   to refresh the glossary without re-scoring everything.

Same Celery decoration pattern as ``content_generation.py``:
``autoretry_for=(Exception,)``, ``max_retries=1``, large
``time_limit`` because Anthropic calls can be slow under load.
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from celery import Task

from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

QUALITY_SOFT_LIMIT = 1800  # 30 min soft
QUALITY_HARD_LIMIT = 2100  # 35 min hard


class QualityCallbackTask(Task):
    """Base task class with structured-log callbacks for quality work."""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info("Quality task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(
            "Quality task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback if einfo else None,
        )


def _make_session_factory(settings):
    """Build an async session factory for Celery's sync entry points.

    Mirrors the pattern in ``content_generation.py`` so we don't share
    engines across tasks (Celery workers fork; sharing engines races).
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


# ---- 1. Per-unit assessment (cheap path) ------------------------------


@celery_app.task(
    bind=True,
    base=QualityCallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    soft_time_limit=300,
    time_limit=360,
    rate_limit="10/m",
)
def assess_unit_task(
    self,
    content_id: str,
    run_id: str | None = None,
    attempt: int = 1,
) -> dict:
    """Assess a single unit; persist the result.

    Called both:
    - Auto via ``link=`` after each generator task (run_id=None).
    - Inside the course sweep's per-unit loop (run_id set).

    When called via link, the previous task's result is passed as
    the first positional arg by Celery — we ignore it because the
    caller already has the content_id.
    """

    async def _run() -> dict:
        from app.ai.claude_service import ClaudeService
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.retriever import SemanticRetriever
        from app.domain.services.quality_agent_service import CourseQualityService
        from app.infrastructure.config.settings import settings

        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                embedding = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding)
                service = CourseQualityService(ClaudeService(), retriever)
                run_uuid = uuid.UUID(run_id) if run_id else None
                report, assessment = await service.assess_unit(
                    content_id=uuid.UUID(content_id),
                    run_id=run_uuid,
                    session=session,
                    attempt_number=attempt,
                )
                await session.commit()
                return {
                    "status": "complete",
                    "content_id": content_id,
                    "score": int(report.quality_score),
                    "needs_regeneration": bool(report.needs_regeneration),
                    "flag_count": len(report.flags),
                    "assessment_id": str(assessment.id),
                }
        except PermissionError as e:
            logger.info(
                "assess_unit_task: skipped (manual_override)",
                content_id=content_id,
                reason=str(e),
            )
            return {"status": "skipped", "reason": "manual_override"}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        return result
    except Exception as exc:
        logger.error(
            "assess_unit_task failed",
            content_id=content_id,
            run_id=run_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc), "content_id": content_id}


# ---- 2. Loop wrapper (assess + regenerate up to MAX_REGEN_ATTEMPTS) ---


@celery_app.task(
    bind=True,
    base=QualityCallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    soft_time_limit=QUALITY_SOFT_LIMIT,
    time_limit=QUALITY_HARD_LIMIT,
    rate_limit="3/m",
)
def assess_and_regenerate_unit_task(
    self,
    content_id: str,
    run_id: str | None = None,
    triggered_by_user_id: str | None = None,
) -> dict:
    """Run the bounded assess→regenerate loop for one unit."""

    async def _run() -> dict:
        from app.ai.claude_service import ClaudeService
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.retriever import SemanticRetriever
        from app.domain.services.quality_agent_service import CourseQualityService
        from app.infrastructure.config.settings import settings

        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                embedding = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding)
                service = CourseQualityService(ClaudeService(), retriever)
                run_uuid = uuid.UUID(run_id) if run_id else None
                user_uuid = uuid.UUID(triggered_by_user_id) if triggered_by_user_id else None
                last = await service.assess_and_regenerate_loop(
                    content_id=uuid.UUID(content_id),
                    run_id=run_uuid,
                    session=session,
                    triggered_by_user_id=user_uuid,
                )
                await session.commit()
                return {
                    "status": "complete",
                    "content_id": content_id,
                    "final_score": float(last.score) if last is not None else None,
                    "attempts": last.attempt_number if last is not None else 0,
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "assess_and_regenerate_unit_task failed",
            content_id=content_id,
            run_id=run_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc), "content_id": content_id}


# ---- 3. Glossary extraction -------------------------------------------


@celery_app.task(
    bind=True,
    base=QualityCallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    soft_time_limit=QUALITY_SOFT_LIMIT,
    time_limit=QUALITY_HARD_LIMIT,
    rate_limit="2/m",
)
def extract_course_glossary_task(self, course_id: str, language: str = "fr") -> dict:
    """Build (or refresh) the canonical glossary for a course."""

    async def _run() -> dict:
        from app.ai.claude_service import ClaudeService
        from app.domain.services.quality_agent_service import CourseQualityService
        from app.infrastructure.config.settings import settings

        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                service = CourseQualityService(ClaudeService(), semantic_retriever=None)
                terms = await service.extract_or_refresh_glossary(
                    course_id=uuid.UUID(course_id),
                    language=language,
                    session=session,
                )
                await session.commit()
                drift = sum(1 for t in terms if t.consistency_status == "drift_detected")
                return {
                    "status": "complete",
                    "course_id": course_id,
                    "language": language,
                    "term_count": len(terms),
                    "drift_count": drift,
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "extract_course_glossary_task failed",
            course_id=course_id,
            language=language,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc), "course_id": course_id}


# ---- 4. Course-wide sweep --------------------------------------------


@celery_app.task(
    bind=True,
    base=QualityCallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 1, "countdown": 30},
    soft_time_limit=QUALITY_HARD_LIMIT * 2,  # course sweeps can take a while
    time_limit=QUALITY_HARD_LIMIT * 2 + 60,
    rate_limit="1/m",
)
def assess_course_task(
    self,
    run_id: str,
    triggered_by_user_id: str | None = None,
) -> dict:
    """Orchestrate a full quality sweep for a course.

    Steps:
    1. Mark run ``status='scoring'``, set ``started_at``.
    2. For each declared course language, run the glossary pre-pass.
    3. Build the cached system blocks ONCE for that language.
    4. For each candidate unit (status NOT IN locked-set,
       regeneration_attempts < MAX), call the assess+loop helper.
    5. Finalize the run with aggregate stats.
    """

    async def _run() -> dict:
        from datetime import datetime

        from sqlalchemy import select

        from app.ai.claude_service import ClaudeService
        from app.ai.prompts.quality import build_cached_system_blocks
        from app.ai.rag.embeddings import EmbeddingService
        from app.ai.rag.retriever import SemanticRetriever
        from app.domain.models.content import GeneratedContent
        from app.domain.models.course import Course
        from app.domain.models.course_quality import CourseQualityRun
        from app.domain.models.module import Module
        from app.domain.services.quality_agent_service import CourseQualityService
        from app.infrastructure.config.settings import settings

        engine, session_factory = _make_session_factory(settings)
        try:
            async with session_factory() as session:
                run = await session.get(CourseQualityRun, uuid.UUID(run_id))
                if run is None:
                    return {"status": "failed", "error": "run_not_found"}
                course = await session.get(Course, run.course_id)
                if course is None:
                    run.status = "failed"
                    run.notes = "course not found"
                    await session.commit()
                    return {"status": "failed", "error": "course_not_found"}

                run.status = "scoring"
                run.started_at = datetime.utcnow()
                await session.commit()

                embedding = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding)
                service = CourseQualityService(ClaudeService(), retriever)

                languages = [
                    lang.strip()
                    for lang in (course.languages or "fr,en").split(",")
                    if lang.strip()
                ]

                processed = 0
                regenerated = 0
                user_uuid = uuid.UUID(triggered_by_user_id) if triggered_by_user_id else None

                for language in languages:
                    # Glossary pre-pass.
                    try:
                        await service.extract_or_refresh_glossary(
                            course_id=run.course_id,
                            language=language,
                            session=session,
                        )
                        await session.commit()
                    except Exception as e:
                        logger.warning(
                            "Glossary pre-pass failed (continuing without)",
                            course_id=str(run.course_id),
                            language=language,
                            error=str(e),
                        )

                    ctx = await service.build_quality_context(
                        course_id=run.course_id,
                        language=language,
                        session=session,
                    )
                    cached_blocks = build_cached_system_blocks(**ctx)

                    # Pull candidate units.
                    candidates_q = (
                        select(GeneratedContent)
                        .join(Module, GeneratedContent.module_id == Module.id)
                        .where(Module.course_id == run.course_id)
                        .where(GeneratedContent.language == language)
                        .where(GeneratedContent.is_manually_edited.is_(False))
                        .where(
                            GeneratedContent.quality_status.notin_(
                                ["regenerating", "manual_override"]
                            )
                        )
                    )
                    candidates_result = await session.execute(candidates_q)
                    candidates = list(candidates_result.scalars().all())

                    for gc in candidates:
                        # Budget check.
                        if run.spent_credits >= run.budget_credits and run.budget_credits > 0:
                            logger.info(
                                "Run budget exhausted — stopping",
                                run_id=run_id,
                                spent=run.spent_credits,
                                budget=run.budget_credits,
                            )
                            run.notes = "budget_exhausted"
                            break

                        try:
                            attempts_before = gc.regeneration_attempts or 0
                            await service.assess_and_regenerate_loop(
                                content_id=gc.id,
                                run_id=run.id,
                                session=session,
                                cached_blocks=cached_blocks,
                                triggered_by_user_id=user_uuid,
                            )
                            await session.refresh(gc)
                            if (gc.regeneration_attempts or 0) > attempts_before:
                                regenerated += 1
                            processed += 1
                            await session.commit()

                            # Course-level early exit check.
                            if processed >= 5:
                                # Only check after some real data accumulated.
                                from sqlalchemy import func as sa_func

                                stat_q = select(
                                    sa_func.count().label("total"),
                                    sa_func.count()
                                    .filter(GeneratedContent.quality_status == "passing")
                                    .label("passing"),
                                ).where(GeneratedContent.last_quality_run_id == run.id)
                                stat_row = (await session.execute(stat_q)).one()
                                total = int(stat_row.total or 0)
                                passing = int(stat_row.passing or 0)
                                if total > 0 and (passing / total) >= 0.92:
                                    # See if any remaining flags are blocker — if not, early-exit.
                                    blocker_q = (
                                        select(GeneratedContent.id)
                                        .where(GeneratedContent.last_quality_run_id == run.id)
                                        .where(
                                            GeneratedContent.quality_flags.contains(
                                                [{"severity": "blocking"}]
                                            )
                                        )
                                        .limit(1)
                                    )
                                    blocker_exists = (
                                        await session.execute(blocker_q)
                                    ).scalar_one_or_none() is not None
                                    if not blocker_exists:
                                        logger.info(
                                            "Course-level early exit",
                                            run_id=run_id,
                                            passing=passing,
                                            total=total,
                                        )
                                        run.notes = "early_exit_92_percent"
                                        break
                        except Exception as e:
                            logger.error(
                                "Per-unit assess failed in sweep",
                                content_id=str(gc.id),
                                run_id=run_id,
                                error=str(e),
                            )
                            # Roll back the failed unit's tx but keep the sweep going.
                            await session.rollback()

                    # End of language loop iteration: commit.
                    await session.commit()

                # Finalize run.
                run.units_regenerated = regenerated
                final = await service.finalize_run(run.id, session)
                await session.commit()
                return {
                    "status": "complete",
                    "run_id": run_id,
                    "units_total": final.units_total,
                    "units_passing": final.units_passing,
                    "units_regenerated": regenerated,
                    "overall_score": float(final.overall_score)
                    if final.overall_score is not None
                    else None,
                }
        finally:
            await engine.dispose()

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error(
            "assess_course_task failed",
            run_id=run_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc), "run_id": run_id}
