"""Celery tasks for AI content generation."""

import contextlib
import hashlib
import uuid
from collections.abc import AsyncIterator

import structlog
from celery import Task
from celery.exceptions import Ignore, SoftTimeLimitExceeded

from app.ai.usage_context import set_ai_context
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

POLL_SOFT_LIMIT = 300
POLL_HARD_LIMIT = 320

#: A module story's time (#2680, story generator v4). The course bible comes
#: first when the course has none (once per course), concurrently with the
#: lessons and covering quizzes that are missing (the lesson and quiz tasks'
#: 300 s each); then the episode plan (one call, ~60 s, and at most one
#: repair), the practice packs concurrently (~65 s each, while the stories are
#: written), and the chapters ONE AFTER ANOTHER, each told after the one
#: before it (~80 s, plus one repair at most), then the rally. A module of 3
#: lessons takes about 8-10 minutes, of 6 about 14; a cold course whose
#: lessons and quizzes must be made first can pass 20. The run keeps a
#: deadline (SOFT - MODULE_STORY_DEADLINE_MARGIN_S) and never starts a story
#: call with less than 240 s left: it stops cleanly and the task dispatches
#: itself again (at most MODULE_STORY_MAX_CONTINUATIONS times). Chapters are
#: cached one by one, so nothing is paid twice. HARD + 60 (the API's dedup
#: TTL, 2520 s) stays under the Redis broker's default 3600 s visibility
#: timeout (acks_late) — but that timeout also counts the wait in a worker's
#: prefetch buffer, so a long-queued run can be delivered again with the same
#: id: the run's PostgreSQL advisory lock (_module_story_lock) turns the
#: second copy away before it pays for anything.
MODULE_STORY_SOFT_LIMIT = 2400
MODULE_STORY_HARD_LIMIT = 2460
#: The run's own deadline comes this long before the soft limit.
MODULE_STORY_DEADLINE_MARGIN_S = 150
#: How many times a module story task dispatches itself to finish a run.
MODULE_STORY_MAX_CONTINUATIONS = 2

#: The API's dedup key for a module story lives this long: claimed for it at
#: dispatch (covering the queue wait), and armed again for it when the task
#: starts (covering the run, which the queue wait must not eat into).
MODULE_STORY_DISPATCH_TTL_S = MODULE_STORY_HARD_LIMIT + 60

#: Connections for a module story: one session per concurrent chapter (6)
#: plus the setup and merge sessions, which are never open during the fan-out.
MODULE_STORY_POOL_SIZE = 8
MODULE_STORY_MAX_OVERFLOW = 2

#: First key of the module story run locks (two int4 keys: namespace, then
#: module and language). PostgreSQL keeps two-key advisory locks apart from
#: single-bigint ones, so these never meet the bible's or the plan's locks
#: (one bigint each), nor story art's (namespace 0x2675).
MODULE_STORY_LOCK_NAMESPACE = 0x2680


def module_story_run_key(module_id: str, language: str) -> str:
    """Redis key naming the task id of the run that holds the module's lock."""
    return f"module_story_run:{module_id}:{language}"


#: What a run turned away by the lock reports when the running copy has
#: another task id (the dedup key is handed to that id). A copy with the
#: running copy's own id stores nothing (``Ignore``): that id stays STARTED.
MODULE_STORY_SKIPPED = {
    "status": "skipped",
    "reason": "module_story_in_progress",
    "content_id": None,
    "is_valid": False,
}

#: How long the module story task waits, before disposing of its engine, for
#: the session closes a soft time limit left running (well inside the 60 s
#: between the soft and the hard limit; a ROLLBACK takes milliseconds).
MODULE_STORY_CLOSE_GRACE_S = 20.0


async def _await_other_tasks(timeout: float) -> None:
    """Wait (bounded) for every task on this loop but the current one to finish.

    A Celery soft time limit arrives as a signal: while every chapter awaits
    the model it lands in the loop's ``select()``, outside any task. Then
    ``asyncio.run``'s teardown cancels every task and the main task's
    TaskGroup cancels the chapters a second time, so a chapter can end while
    its ``AsyncSession``'s shielded close task still holds a connection. The
    engine must not be disposed before those closes return their connections,
    or they stay open in the (long-lived) worker process.
    """
    import asyncio

    current = asyncio.current_task()
    others = {task for task in asyncio.all_tasks() if task is not current}
    if others:
        await asyncio.wait(others, timeout=timeout)


def _safe_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Parse task-arg ids (strings over the wire) for ledger attribution."""
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


class CallbackTask(Task):
    """Base task class with callbacks for content generation."""

    def on_success(self, retval, task_id, args, kwargs):
        """Called when task succeeds."""
        logger.info("Content generation task completed", task_id=task_id, result=retval)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called when task fails."""
        logger.error(
            "Content generation task failed",
            task_id=task_id,
            exception=str(exc),
            traceback=einfo.traceback,
        )


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="5/m",  # 5 tasks per minute
)
def generate_lesson_bulk(self, module_id: str, language: str = "fr", country: str = "CI") -> dict:
    """Generate lessons for a module in bulk (async background task).

    Args:
        module_id: UUID of the module
        language: Language code (fr/en)
        country: Country code for contextualization

    Returns:
        dict: Task result with generated lesson IDs
    """
    logger.info(
        "Starting bulk lesson generation",
        module_id=module_id,
        language=language,
        country=country,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement lesson generation logic
        # This will use the RAG pipeline from app.ai.rag.generator
        # For now, return a placeholder
        result = {
            "module_id": module_id,
            "language": language,
            "country": country,
            "lessons_generated": 0,
            "status": "pending_implementation",
        }

        logger.info(
            "Bulk lesson generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Bulk lesson generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="10/m",  # 10 tasks per minute
)
def generate_quiz_questions(
    self, module_id: str, count: int = 20, difficulty: str = "medium"
) -> dict:
    """Generate quiz questions for a module.

    Args:
        module_id: UUID of the module
        count: Number of questions to generate
        difficulty: Question difficulty level

    Returns:
        dict: Task result with generated question IDs
    """
    logger.info(
        "Starting quiz question generation",
        module_id=module_id,
        count=count,
        difficulty=difficulty,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement quiz generation logic
        # This will use the RAG pipeline and CAT algorithm
        result = {
            "module_id": module_id,
            "questions_generated": 0,
            "difficulty": difficulty,
            "status": "pending_implementation",
        }

        logger.info(
            "Quiz question generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Quiz question generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 60},
    rate_limit="15/m",  # 15 tasks per minute
)
def generate_flashcards(self, module_id: str, language: str = "fr", count: int = 30) -> dict:
    """Generate flashcards for a module.

    Args:
        module_id: UUID of the module
        language: Language for flashcard content
        count: Number of flashcards to generate

    Returns:
        dict: Task result with generated flashcard IDs
    """
    logger.info(
        "Starting flashcard generation",
        module_id=module_id,
        language=language,
        count=count,
        task_id=self.request.id,
    )

    try:
        # TODO: Implement flashcard generation logic
        result = {
            "module_id": module_id,
            "language": language,
            "flashcards_generated": 0,
            "status": "pending_implementation",
        }

        logger.info(
            "Flashcard generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )

        return result

    except Exception as exc:
        logger.error(
            "Flashcard generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_lesson_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
    force_regenerate: bool = False,
) -> dict:
    """Generate lesson content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        force_regenerate: Skip the cache read and overwrite the cached row
            (#2561 — the Refresh button was a no-op without this)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.lesson_service import LessonGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async lesson generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("lesson_generation", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = LessonGenerationService(ClaudeService(), retriever)
                lesson = await service.get_or_generate_lesson(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                    force_regenerate=force_regenerate,
                )
                return {"status": "complete", "content_id": str(lesson.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async lesson generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        # Auto-trigger per-unit quality assessment (#2215). Best-effort
        # — never block the generation result on the assessment task.
        try:
            if result.get("status") == "complete" and result.get("content_id"):
                from app.tasks.quality_assessment import assess_and_regenerate_unit_task

                assess_and_regenerate_unit_task.apply_async(
                    kwargs={"content_id": result["content_id"]},
                    priority=5,
                )
        except Exception as exc:
            logger.warning(
                "Quality auto-assess dispatch failed (non-fatal)",
                content_id=result.get("content_id"),
                error=str(exc),
            )
        return result
    except Exception as exc:
        logger.error(
            "Async lesson generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_case_study_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
    force_regenerate: bool = False,
) -> dict:
    """Generate case study content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        force_regenerate: Skip the cache read and overwrite the cached row
            (#2561 — the Refresh button was a no-op without this)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.lesson_service import CaseStudyGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async case study generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("case_study", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = CaseStudyGenerationService(ClaudeService(), retriever)
                case_study = await service.get_or_generate_case_study(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                    force_regenerate=force_regenerate,
                )
                return {"status": "complete", "content_id": str(case_study.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async case study generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        try:
            if result.get("status") == "complete" and result.get("content_id"):
                from app.tasks.quality_assessment import assess_and_regenerate_unit_task

                assess_and_regenerate_unit_task.apply_async(
                    kwargs={"content_id": result["content_id"]},
                    priority=5,
                )
        except Exception as exc:
            logger.warning(
                "Quality auto-assess dispatch failed (non-fatal)",
                content_id=result.get("content_id"),
                error=str(exc),
            )
        return result
    except Exception as exc:
        logger.error(
            "Async case study generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


#: Re-arm the dedup key for the task that starts: when it still names the
#: task, or when it expired while the task was queued and nobody has claimed
#: it since. A key another dispatch now holds is left alone.
_HOLD_IF_OWNER_OR_FREE_SCRIPT = """
local holder = redis.call("get", KEYS[1])
if holder == ARGV[1] or not holder then
  redis.call("set", KEYS[1], ARGV[1], "EX", ARGV[2])
  return 1
end
return 0
"""


def _hold_story_dispatch(dedup_key: str | None, task_id: str | None, ttl_s: int) -> int | None:
    """Arm the API's dedup key for ``ttl_s`` from now, as the task starts (best effort).

    The key was claimed at dispatch with the same TTL, so the time the task
    waited in the queue (behind other long tasks, in a worker's prefetch
    buffer) would otherwise come off its run: the key could expire while the
    task still runs, and the next view would dispatch a second, paid,
    generation of the same chapters.

    Returns the script's answer: 1 when the key now names this task, 0 when
    another task holds it, None without a key or task id or when Redis fails.
    Callers that only re-arm may ignore it.
    """
    if not dedup_key or not task_id:
        return None
    try:
        import redis

        from app.infrastructure.config.settings import settings

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            return int(client.eval(_HOLD_IF_OWNER_OR_FREE_SCRIPT, 1, dedup_key, task_id, ttl_s))
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Story dispatch key not re-armed", key=dedup_key, error=str(exc))
        return None


def _release_story_dispatch(dedup_key: str | None, task_id: str | None) -> None:
    """Release the API's dedup key if it still names this task (best effort).

    A compare-and-delete, so a key another request has claimed since is left
    alone. Uses a short-lived synchronous client: the task's event loop is
    gone by the time this runs.
    """
    if not dedup_key or not task_id:
        return
    try:
        import redis

        from app.domain.services.story_from_lesson_service import RELEASE_IF_OWNER_SCRIPT
        from app.infrastructure.config.settings import settings

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            client.eval(RELEASE_IF_OWNER_SCRIPT, 1, dedup_key, task_id)
        finally:
            client.close()
    except Exception as exc:
        # The key expires on its own (the task's hard limit plus slack).
        logger.warning("Story dispatch key not released", key=dedup_key, error=str(exc))


def module_story_lock_key(module_id: str, language: str) -> tuple[int, int]:
    """The run lock's key: ``(namespace, signed int4 of the module and language)``."""
    digest = hashlib.sha256(f"module_story:{module_id}:{language}".encode()).digest()
    return MODULE_STORY_LOCK_NAMESPACE, int.from_bytes(digest[:4], "big", signed=True)


@contextlib.asynccontextmanager
async def _module_story_lock(engine, module_id: str, language: str) -> AsyncIterator[bool]:
    """Hold the (module, language) PostgreSQL advisory lock for a run; yield whether taken.

    ``pg_try_advisory_lock`` on a connection of its own, kept for the whole
    run in autocommit (no transaction stays open), then unlocked. The lock is
    the database's, so it holds whatever Redis says: a broker redelivery of
    the same task id (``acks_late``, a message unacked past the visibility
    timeout while it waited in a prefetch buffer), which the dedup key naming
    that id lets through, finds it taken. A connection that dies frees it,
    and the task's engine is disposed after every run.
    """
    import sqlalchemy as sa

    namespace, key = module_story_lock_key(module_id, language)
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        taken = bool(
            (
                await connection.execute(sa.select(sa.func.pg_try_advisory_lock(namespace, key)))
            ).scalar()
        )
        try:
            yield taken
        finally:
            if taken:
                with contextlib.suppress(Exception):
                    await connection.execute(sa.select(sa.func.pg_advisory_unlock(namespace, key)))


def _run_holder(key: str, task_id: str | None, *, release: bool = False) -> str | None:
    """Record (or, with ``release``, clear) the run holding the lock; best effort.

    Recording returns ``None``. Without ``task_id`` it reads the holder's id.
    """
    try:
        import redis

        from app.domain.services.story_from_lesson_service import RELEASE_IF_OWNER_SCRIPT
        from app.infrastructure.config.settings import settings

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            if task_id is None:
                return client.get(key)
            if release:
                client.eval(RELEASE_IF_OWNER_SCRIPT, 1, key, task_id)
            else:
                client.set(key, task_id, ex=MODULE_STORY_DISPATCH_TTL_S)
            return None
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Module story run holder not recorded", key=key, error=str(exc))
        return None


def _hand_key_to(dedup_key: str | None, task_id: str | None, holder: str) -> None:
    """Give the dedup key from this task to the run that holds the lock (best effort)."""
    if not dedup_key or not task_id:
        return
    try:
        import redis

        from app.infrastructure.config.settings import settings

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            client.eval(
                _HAND_OVER_SCRIPT, 1, dedup_key, task_id, holder, MODULE_STORY_DISPATCH_TTL_S
            )
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Story dispatch key not handed to the run", key=dedup_key, error=str(exc))


def _continue_module_story(
    module_id: str,
    language: str,
    country: str,
    level: int,
    dedup_key: str | None,
    continuation: int,
    task_id: str | None,
) -> str | None:
    """Dispatch the next part of a module story run; hand it the dedup key.

    The new task's id is made first, so the task is marked as dispatched and
    vouched for (``content_task:{id}``, ``content_task_owner:{id}``, as the
    API does for the first task) before it is queued: a learner who joins it
    while it waits in the queue sees it pending, never ``task_lost``. Then the
    id is written to the API's dedup key (compare-and-set from this task's
    id), so a learner's next GET joins the continuation instead of starting
    another run. ``None`` when the dispatch failed.
    """
    from app.api.v1._task_status import dispatch_markers

    next_id = str(uuid.uuid4())
    client = None
    try:
        import redis

        from app.infrastructure.config.settings import settings

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        for key, ttl, value in dispatch_markers(next_id, dedup_key, MODULE_STORY_DISPATCH_TTL_S):
            client.setex(key, ttl, value)
    except Exception as exc:
        logger.warning("Continuation not marked as dispatched", task_id=next_id, error=str(exc))
    try:
        try:
            generate_module_story_task.apply_async(
                kwargs={
                    "module_id": module_id,
                    "language": language,
                    "country": country,
                    "level": level,
                    "force_regenerate": False,
                    "dedup_key": dedup_key,
                    "continuation": continuation,
                },
                task_id=next_id,
            )
        except Exception as exc:
            logger.error("Module story continuation not dispatched", error=str(exc)[:300])
            return None
        if dedup_key and task_id and client is not None:
            try:
                client.eval(
                    _HAND_OVER_SCRIPT,
                    1,
                    dedup_key,
                    task_id,
                    next_id,
                    MODULE_STORY_DISPATCH_TTL_S,
                )
            except Exception as exc:
                logger.warning("Story dispatch key not handed over", key=dedup_key, error=str(exc))
        return next_id
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


#: Give the dedup key to the continuation: when it still names this task, or
#: when it has expired and nobody has claimed it since.
_HAND_OVER_SCRIPT = """
local holder = redis.call("get", KEYS[1])
if holder == ARGV[1] or not holder then
  redis.call("set", KEYS[1], ARGV[2], "EX", ARGV[3])
  return 1
end
return 0
"""


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=MODULE_STORY_SOFT_LIMIT,
    time_limit=MODULE_STORY_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_module_story_task(
    self,
    module_id: str,
    language: str,
    country: str = "CI",
    level: int = 1,
    force_regenerate: bool = False,
    dedup_key: str | None = None,
    continuation: int = 0,
) -> dict:
    """Generate a module's story and cache it in ``story_courses`` (contract C-3).

    Dispatched by ``GET /story-courses/module/{module_id}`` the first time a
    learner opens the module's story, or when it is stale. Every lesson
    chapter that is missing or stale is made (generating the unit's lesson
    and its covering quiz first when they are missing), concurrently, each in
    its own session, then the module story is assembled from the cached
    chapters (:class:`~app.domain.services.story_module_service.ModuleStoryService`).
    ``country``/``level`` only choose which missing content is generated and
    which cached rows are preferred: one story serves every learner of the
    module in that language.

    Returns ``{"status": "complete", "content_id": <story_courses id>,
    "is_valid": bool}``; a story that does not validate is stored as a draft
    and still reports ``complete`` (the client's re-fetch merges it once more
    at no model cost, then gets 409). When the run reaches its deadline
    before a story call (#2680) it stops cleanly and dispatches itself again
    with ``continuation + 1`` (at most :data:`MODULE_STORY_MAX_CONTINUATIONS`),
    handing it the dedup key, and reports ``{"status": "complete",
    "continued_by": <task id>, "content_id": None}``: the client's re-fetch
    joins the continuation (202). Otherwise
    ``{"status": "failed", "content_id": None, "is_valid": False, "error":
    ...}``, with ``"failed_units"`` when chapters failed: the module row is
    then not written, and the chapters that were made stay cached for the
    next open. On the soft time limit the chapters in flight are cancelled
    (their sessions roll back) and the task reports ``time_limit_exceeded``.

    ``dedup_key`` is the API's Redis key for this (module, language); it is
    released when the task ends, however it ends — except by a copy turned
    away by the run lock (:func:`_module_story_lock`, a broker redelivery of
    the same id while it runs), which reports ``{"status": "skipped"}`` and
    leaves the key to the running copy. Never retried (``autoretry_for`` is
    unset): a retry would pay for the chapters again.
    """
    import asyncio
    import time

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.ai_usage_event import FEATURE_STORY_GENERATION
    from app.domain.services.lesson_service import LessonGenerationService
    from app.domain.services.quiz_service import QuizService
    from app.domain.services.story_module_service import (
        ChapterGenerationFailed,
        ModuleStoryService,
        StoryDeadlineReached,
    )
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async module story generation",
        module_id=module_id,
        language=language,
        force_regenerate=force_regenerate,
        continuation=continuation,
        task_id=self.request.id,
    )
    deadline = time.monotonic() + MODULE_STORY_SOFT_LIMIT - MODULE_STORY_DEADLINE_MARGIN_S

    async def _run() -> dict:
        set_ai_context(FEATURE_STORY_GENERATION, module_id=_safe_uuid(module_id))  # ledger
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=MODULE_STORY_POOL_SIZE,
            max_overflow=MODULE_STORY_MAX_OVERFLOW,
        )
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with _module_story_lock(engine, module_id, language) as taken:
                if not taken:
                    logger.warning(
                        "Module story run skipped: another run holds the module's lock",
                        module_id=module_id,
                        language=language,
                        task_id=self.request.id,
                    )
                    return dict(MODULE_STORY_SKIPPED)
                _run_holder(run_key, self.request.id)
                claude = ClaudeService()
                # Shared by every chapter: both hold configuration only, and the
                # embedding client is safe to use concurrently on one loop.
                retriever = SemanticRetriever(
                    EmbeddingService(
                        api_key=settings.openai_api_key, model=settings.embedding_model
                    )
                )
                from app.infrastructure.storage.s3 import S3StorageService

                service = ModuleStoryService(
                    claude,
                    LessonGenerationService(claude, retriever),
                    QuizService(claude, retriever),
                    # #2681: a figure whose binary is gone is never offered.
                    figure_storage=S3StorageService(),
                )
                record = await service.get_or_generate_module_story(
                    uuid.UUID(module_id),
                    language,
                    session_factory,
                    level=level,
                    country=country,
                    # A continuation never forces: the chapters already told are kept.
                    force_regenerate=force_regenerate and continuation == 0,
                    deadline=deadline,
                )
                return {
                    "status": "complete",
                    "content_id": str(record.id),
                    "is_valid": bool(record.is_valid),
                }
        finally:
            # A chapter session's close can outlive its chapter on a soft
            # time limit (see _await_other_tasks): let it finish first.
            await _await_other_tasks(MODULE_STORY_CLOSE_GRACE_S)
            await engine.dispose()

    failed: dict = {"status": "failed", "content_id": None, "is_valid": False}
    run_key = module_story_run_key(module_id, language)
    release_key = True
    try:
        _hold_story_dispatch(dedup_key, self.request.id, MODULE_STORY_DISPATCH_TTL_S)
        result = asyncio.run(_run())
        if result == MODULE_STORY_SKIPPED:
            # Another copy is telling this story: its key is left alone.
            release_key = False
            holder = _run_holder(run_key, None)
            if holder is None or holder == self.request.id:
                # A redelivery of the running task's own id: store nothing, so
                # that id stays STARTED and learners keep joining it.
                raise Ignore()
            # Another id runs it: learners join that one.
            _hand_key_to(dedup_key, self.request.id, holder)
            return {**MODULE_STORY_SKIPPED, "running": holder}
        logger.info(
            "Async module story generation completed",
            module_id=module_id,
            language=language,
            result=result,
            task_id=self.request.id,
        )
        return result
    except SoftTimeLimitExceeded:
        logger.warning(
            "Module story generation hit its soft time limit; the module story was not written",
            module_id=module_id,
            language=language,
            task_id=self.request.id,
        )
        return {**failed, "error": "time_limit_exceeded"}
    except StoryDeadlineReached as exc:
        if continuation >= MODULE_STORY_MAX_CONTINUATIONS:
            logger.warning(
                "Module story stopped at its deadline; no continuation left",
                module_id=module_id,
                language=language,
                told=exc.told,
                task_id=self.request.id,
            )
            return {**failed, "error": "time_limit_exceeded", "told": exc.told}
        next_id = _continue_module_story(
            module_id, language, country, level, dedup_key, continuation + 1, self.request.id
        )
        if next_id is None:
            return {**failed, "error": "time_limit_exceeded", "told": exc.told}
        logger.info(
            "Module story continues in a new task",
            module_id=module_id,
            language=language,
            told=exc.told,
            continuation=continuation + 1,
            next_task_id=next_id,
            task_id=self.request.id,
        )
        return {
            "status": "complete",
            "content_id": None,
            "is_valid": False,
            "continued_by": next_id,
            "told": exc.told,
        }
    except ChapterGenerationFailed as exc:
        logger.warning(
            "Module story generation failed: chapters could not be made",
            module_id=module_id,
            language=language,
            failed_units=exc.failed_units,
            task_id=self.request.id,
        )
        return {**failed, "error": "chapter_generation_failed", "failed_units": exc.failed_units}
    except Ignore:
        raise
    except Exception as exc:
        logger.error(
            "Async module story generation failed",
            module_id=module_id,
            language=language,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {**failed, "error": str(exc)}
    finally:
        if release_key:
            _release_story_dispatch(dedup_key, self.request.id)
            _run_holder(run_key, self.request.id, release=True)


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_quiz_task(
    self,
    module_id: str,
    unit_id: str,
    language: str,
    country: str,
    level: int,
    num_questions: int = 10,
) -> dict:
    """Generate quiz content via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        num_questions: Number of questions to generate

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.quiz_service import QuizService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async quiz generation",
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        country=country,
        level=level,
        num_questions=num_questions,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("quiz_generation", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = QuizService(ClaudeService(), retriever)
                quiz = await service.get_or_generate_quiz(
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    country=country,
                    level=level,
                    num_questions=num_questions,
                    session=session,
                )
                return {"status": "complete", "content_id": str(quiz.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async quiz generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        try:
            if result.get("status") == "complete" and result.get("content_id"):
                from app.tasks.quality_assessment import assess_and_regenerate_unit_task

                assess_and_regenerate_unit_task.apply_async(
                    kwargs={"content_id": result["content_id"]},
                    priority=5,
                )
        except Exception as exc:
            logger.warning(
                "Quality auto-assess dispatch failed (non-fatal)",
                content_id=result.get("content_id"),
                error=str(exc),
            )
        return result
    except Exception as exc:
        logger.error(
            "Async quiz generation failed",
            module_id=module_id,
            unit_id=unit_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 3, "countdown": 120},
    soft_time_limit=360,
    time_limit=400,
    rate_limit="5/m",
    priority=5,
)
def generate_country_content_task(
    self,
    module_id: str,
    unit_id: str,
    content_type: str,
    language: str,
    level: int,
    country: str,
    user_id: str,
) -> dict:
    """Generate country-targeted content in background after a country-fallback was served.

    Args:
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        content_type: One of "lesson", "quiz", "case"
        language: Content language (fr/en)
        level: User competency level (1-4)
        country: Target country code for generation
        user_id: UUID of the requesting user (for logging)

    Returns:
        dict with status and content_id (or error)
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.content import GeneratedContent
    from app.domain.services.country_utils import canonicalize_country
    from app.infrastructure.config.settings import settings

    # Defensive: dispatch sites already canonicalize, but never let a legacy
    # slug (e.g. "burkina-faso") reach the write path and create a duplicate
    # cache row that the ISO-keyed lookup can never match.
    country = canonicalize_country(country)

    logger.info(
        "Starting country-targeted background generation",
        module_id=module_id,
        unit_id=unit_id,
        content_type=content_type,
        language=language,
        level=level,
        country=country,
        user_id=user_id,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context(user_id=_safe_uuid(user_id), module_id=_safe_uuid(module_id))  # #2629
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                from app.domain.services._unit_resolution import resolve_module_unit_id

                cgen_unit_uuid = await resolve_module_unit_id(
                    session, uuid.UUID(module_id), unit_id
                )
                existing_query = (
                    select(GeneratedContent)
                    .where(
                        GeneratedContent.content_type == content_type,
                        GeneratedContent.language == language,
                        GeneratedContent.level == level,
                        GeneratedContent.country_context == country,
                    )
                    .limit(1)
                )
                if cgen_unit_uuid is not None:
                    existing_query = existing_query.where(
                        GeneratedContent.module_unit_id == cgen_unit_uuid
                    )
                else:
                    existing_query = existing_query.where(
                        GeneratedContent.module_id == uuid.UUID(module_id),
                        GeneratedContent.module_unit_id.is_(None),
                        GeneratedContent.content["unit_id"].astext == unit_id,
                    )
                existing = await session.execute(existing_query)
                if existing.scalars().first():
                    logger.info(
                        "Country-targeted content already exists, skipping generation",
                        module_id=module_id,
                        unit_id=unit_id,
                        content_type=content_type,
                        language=language,
                        level=level,
                        country=country,
                    )
                    return {"status": "skipped", "reason": "already_exists"}

                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)

                if content_type == "lesson":
                    from app.domain.services.lesson_service import LessonGenerationService

                    service = LessonGenerationService(ClaudeService(), retriever)
                    # force_regenerate bypasses the cache-read country fallback.
                    # We already confirmed above that the exact-country row is
                    # absent, so without this the service would return another
                    # country's fallback row and re-dispatch THIS task — an
                    # infinite loop that never generates the target country (#2591).
                    result_obj = await service.get_or_generate_lesson(
                        module_id=uuid.UUID(module_id),
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        level=level,
                        session=session,
                        force_regenerate=True,
                    )
                    from app.domain.services.lesson_service import (
                        extract_lesson_text,
                    )

                    c = getattr(result_obj, "content", None)
                    lesson_text = extract_lesson_text(c) if c else ""
                    generate_lesson_audio.delay(
                        str(result_obj.id),
                        module_id,
                        unit_id,
                        language,
                        lesson_text[:4000],
                    )
                    logger.info(
                        "Country-targeted lesson ready",
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        content_id=str(result_obj.id),
                    )
                    return {"status": "complete", "content_id": str(result_obj.id)}

                elif content_type == "quiz":
                    from app.domain.services.platform_settings_service import (
                        PlatformSettingsService,
                    )
                    from app.domain.services.quiz_service import QuizService

                    settings_svc = PlatformSettingsService()
                    num_questions = int(await settings_svc.get("quiz-unit-questions-count") or 10)
                    service = QuizService(ClaudeService(), retriever)
                    # force_regenerate: generate the exact target country instead
                    # of returning a fallback row and self-dispatching (#2591).
                    result_obj = await service.get_or_generate_quiz(
                        module_id=uuid.UUID(module_id),
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        level=level,
                        num_questions=num_questions,
                        session=session,
                        force_regenerate=True,
                    )
                    logger.info(
                        "Country-targeted quiz ready",
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        content_id=str(result_obj.id),
                    )
                    return {"status": "complete", "content_id": str(result_obj.id)}

                elif content_type == "case":
                    from app.domain.services.lesson_service import CaseStudyGenerationService

                    service = CaseStudyGenerationService(ClaudeService(), retriever)
                    # force_regenerate: generate the exact target country instead
                    # of returning a fallback row and self-dispatching (#2591).
                    result_obj = await service.get_or_generate_case_study(
                        module_id=uuid.UUID(module_id),
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        level=level,
                        session=session,
                        force_regenerate=True,
                    )
                    logger.info(
                        "Country-targeted case study ready",
                        unit_id=unit_id,
                        language=language,
                        country=country,
                        content_id=str(result_obj.id),
                    )
                    return {"status": "complete", "content_id": str(result_obj.id)}

                else:
                    logger.warning(
                        "Unknown content_type for country generation",
                        content_type=content_type,
                    )
                    return {"status": "failed", "error": f"unknown content_type: {content_type}"}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        return result
    except Exception as exc:
        logger.error(
            "Country-targeted background generation failed",
            module_id=module_id,
            unit_id=unit_id,
            content_type=content_type,
            language=language,
            country=country,
            exception=str(exc),
            retries=self.request.retries,
            task_id=self.request.id,
        )
        # Re-raise so `autoretry_for` re-queues transient failures (e.g. an
        # upstream 429/quota blip). Swallowing into a "failed" dict here would
        # defeat the retry config and leave the requested country's row missing
        # forever, permanently stranding the learner on the fallback country.
        raise


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=POLL_SOFT_LIMIT,
    time_limit=POLL_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_flashcard_task(
    self,
    module_id: str,
    language: str,
    country: str,
    level: int,
) -> dict:
    """Generate flashcard set via RAG + Claude, store in generated_content cache.

    Args:
        module_id: UUID of the module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)

    Returns:
        dict with status and content_id
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.services.flashcard_service import FlashcardGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting async flashcard generation",
        module_id=module_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("flashcard_generation", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                service = FlashcardGenerationService(ClaudeService(), retriever)
                flashcard_set = await service.get_or_generate_flashcard_set(
                    module_id=uuid.UUID(module_id),
                    language=language,
                    country=country,
                    level=level,
                    session=session,
                )
                return {"status": "complete", "content_id": str(flashcard_set.id)}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Async flashcard generation completed",
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        try:
            if result.get("status") == "complete" and result.get("content_id"):
                from app.tasks.quality_assessment import assess_and_regenerate_unit_task

                assess_and_regenerate_unit_task.apply_async(
                    kwargs={"content_id": result["content_id"]},
                    priority=5,
                )
        except Exception as exc:
            logger.warning(
                "Quality auto-assess dispatch failed (non-fatal)",
                content_id=result.get("content_id"),
                error=str(exc),
            )
        return result
    except Exception as exc:
        logger.error(
            "Async flashcard generation failed",
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=120,
    time_limit=150,
    rate_limit="5/m",
)
def generate_lesson_image(
    self,
    lesson_id: str,
    module_id: str,
    unit_id: str,
    lesson_content: str,
) -> dict:
    """Generate an illustration for a lesson asynchronously (fire-and-forget).

    Args:
        lesson_id: UUID of the lesson (GeneratedContent.id)
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        lesson_content: Full lesson text used for concept extraction

    Returns:
        dict with image_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.image_service import ImageGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting lesson image generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("image_generation", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                # Guard: skip if image already exists for this lesson
                from sqlalchemy import select as sa_select

                from app.domain.models.generated_image import GeneratedImage

                existing = await session.execute(
                    sa_select(GeneratedImage)
                    .where(
                        GeneratedImage.lesson_id == uuid.UUID(lesson_id),
                        GeneratedImage.status.in_(["ready", "generating", "pending"]),
                    )
                    .limit(1)
                )
                existing_image = existing.scalar_one_or_none()
                if existing_image is not None:
                    logger.info(
                        "Image already exists — skipping task",
                        lesson_id=lesson_id,
                        image_id=str(existing_image.id),
                        status=existing_image.status,
                    )
                    return {"image_id": str(existing_image.id), "status": existing_image.status}

                service = ImageGenerationService()
                image = await service.generate_for_lesson(
                    lesson_id=uuid.UUID(lesson_id),
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    lesson_content=lesson_content,
                    session=session,
                )
                return {"image_id": str(image.id), "status": image.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson image generation completed",
            lesson_id=lesson_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Lesson image generation failed",
            lesson_id=lesson_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"image_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=120,
    time_limit=150,
    rate_limit="5/m",
)
def generate_lesson_audio(
    self,
    lesson_id: str,
    module_id: str,
    unit_id: str,
    language: str,
    lesson_content: str,
) -> dict:
    """Generate an audio summary for a lesson asynchronously (fire-and-forget).

    Args:
        lesson_id: UUID of the lesson (GeneratedContent.id)
        module_id: UUID of the module
        unit_id: Unit identifier within the module
        language: Language code (fr/en)
        lesson_content: Lesson text used for script generation

    Returns:
        dict with audio_id and status
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.lesson_audio_service import LessonAudioService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting lesson audio generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("lesson_audio", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = LessonAudioService()
                audio = await service.generate_for_lesson(
                    lesson_id=uuid.UUID(lesson_id),
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    lesson_content=lesson_content,
                    session=session,
                )
                return {"audio_id": str(audio.id), "status": audio.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson audio generation completed",
            lesson_id=lesson_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Lesson audio generation failed",
            lesson_id=lesson_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"audio_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=120,
    time_limit=150,
    rate_limit="5/m",
)
def generate_lesson_video(
    self,
    lesson_id: str,
    module_id: str,
    unit_id: str,
    language: str,
    lesson_content: str,
) -> dict:
    """Dispatch a HeyGen lesson video summary (fire-and-forget).

    Admin-triggered only — unlike ``generate_lesson_audio`` which
    fires automatically when a lesson is generated, this task is
    only dispatched from the explicit
    ``POST /api/v1/video/lesson/{lesson_id}/generate`` endpoint so
    tenants don't eat HeyGen's per-minute cost for every auto-
    prefetched lesson.

    Fire-and-forget: the task only KICKS OFF the HeyGen render —
    ``poll_pending_heygen_videos`` (Celery-beat, 60 s cadence)
    finalizes the row once HeyGen finishes rendering (~10 min P50).

    Feature-flag gated: no-op when ``video-summary-feature-enabled``
    is false so admins can toggle the whole flow from the settings
    UI without touching code.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.domain.services.lesson_video_service import LessonVideoService
    from app.domain.services.platform_settings_service import SettingsCache
    from app.infrastructure.config.settings import settings

    if not bool(SettingsCache.instance().get("video-summary-feature-enabled", False)):
        logger.info(
            "Lesson video skipped (feature disabled)",
            lesson_id=lesson_id,
            task_id=self.request.id,
        )
        return {"media_id": None, "status": "skipped", "reason": "feature_off"}

    logger.info(
        "Starting lesson video generation",
        lesson_id=lesson_id,
        module_id=module_id,
        unit_id=unit_id,
        language=language,
        task_id=self.request.id,
    )

    async def _run() -> dict:
        set_ai_context("lesson_generation", module_id=_safe_uuid(module_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                service = LessonVideoService()
                media = await service.generate_for_lesson(
                    lesson_id=uuid.UUID(lesson_id),
                    module_id=uuid.UUID(module_id),
                    unit_id=unit_id,
                    language=language,
                    lesson_content=lesson_content,
                    session=session,
                )
                return {"media_id": str(media.id), "status": media.status}
        finally:
            await engine.dispose()

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson video dispatch completed",
            lesson_id=lesson_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Lesson video generation failed",
            lesson_id=lesson_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"media_id": None, "status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=360,
    time_limit=400,
    rate_limit="3/m",
    priority=3,
)
def prefetch_next_lessons_task(
    self,
    user_id: str,
    module_id: str,
    current_unit_id: str,
    language: str,
    country: str,
    level: int,
    module_number: int | None = None,
) -> dict:
    """Pre-generate the next 2 lessons after current_unit_id for a learner.

    Called after registration, quiz pass, or module unlock to eliminate
    the 'Génération du contenu...' wait on first access.

    Args:
        user_id: UUID of the learner
        module_id: UUID string of the current module, or empty string if module_number given
        current_unit_id: Unit number like '1.1'; empty string means start of module
        language: Content language (fr/en)
        country: Country code for contextualization
        level: User competency level (1-4)
        module_number: Module number (e.g. 1 for M01); used when module_id is empty

    Returns:
        dict with prefetched unit_ids, skipped (already cached), and errors
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.content import GeneratedContent
    from app.domain.models.module import Module
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.services.lesson_service import LessonGenerationService
    from app.infrastructure.config.settings import settings

    logger.info(
        "Starting lesson prefetch",
        user_id=user_id,
        module_id=module_id,
        current_unit_id=current_unit_id,
        language=language,
        country=country,
        level=level,
        task_id=self.request.id,
    )

    async def _get_next_units(
        session: AsyncSession,
        module_uuid: uuid.UUID,
        current_unit_id: str,
        count: int = 2,
    ) -> list[tuple[str, str]]:
        """Return (unit_id, content_type) pairs for the next N units after current_unit_id."""
        module_result = await session.execute(select(Module).where(Module.id == module_uuid))
        module = module_result.scalar_one_or_none()
        if not module:
            return []

        units_result = await session.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == module_uuid)
            .order_by(ModuleUnit.order_index)
        )
        all_units = list(units_result.scalars().all())

        current_idx = -1
        if current_unit_id:
            for i, u in enumerate(all_units):
                # Use canonical unit_number ("1.1") — the M01-U01 format was
                # removed by migration 081 (#1897).
                if u.unit_number == current_unit_id:
                    current_idx = i
                    break

        next_units: list[tuple[str, str]] = []
        for u in all_units[current_idx + 1 :]:
            uid = u.unit_number
            raw_type = (u.unit_type or "").lower().replace("-", "_").replace(" ", "_")
            if "quiz" in raw_type or "evaluation" in raw_type or "évaluation" in raw_type:
                content_type = "quiz"
            elif "case" in raw_type or "etude" in raw_type or "étude" in raw_type:
                content_type = "case_study"
            else:
                content_type = "lesson"
            next_units.append((uid, content_type))
            if len(next_units) >= count:
                break

        return next_units

    async def _is_cached(
        session: AsyncSession,
        module_uuid: uuid.UUID,
        unit_id: str,
        content_type: str,
        language: str,
        level: int,
        country: str,
    ) -> bool:
        """Return True if content already exists in generated_content cache."""
        from app.domain.services._unit_resolution import resolve_module_unit_id

        unit_uuid = await resolve_module_unit_id(session, module_uuid, unit_id)
        cache_query = select(GeneratedContent.id).where(
            GeneratedContent.content_type == content_type,
            GeneratedContent.language == language,
        )
        if unit_uuid is not None:
            cache_query = cache_query.where(GeneratedContent.module_unit_id == unit_uuid)
        else:
            cache_query = cache_query.where(
                GeneratedContent.module_id == module_uuid,
                GeneratedContent.module_unit_id.is_(None),
                GeneratedContent.content["unit_id"].astext == unit_id,
            )
        result = await session.execute(cache_query)
        return result.scalar_one_or_none() is not None

    async def _run() -> dict:
        # ledger (#2629)
        set_ai_context(
            "lesson_generation", user_id=_safe_uuid(user_id), module_id=_safe_uuid(module_id)
        )
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        prefetched: list[str] = []
        skipped: list[str] = []
        errors: list[str] = []

        try:
            async with session_factory() as session:
                if module_id:
                    module_uuid = uuid.UUID(module_id)
                elif module_number is not None:
                    mod_result = await session.execute(
                        select(Module).where(Module.module_number == module_number)
                    )
                    mod = mod_result.scalar_one_or_none()
                    if not mod:
                        logger.warning(
                            "Module not found for prefetch",
                            module_number=module_number,
                            user_id=user_id,
                        )
                        return {
                            "status": "skipped",
                            "reason": "module_not_found",
                            "prefetched": [],
                            "skipped": [],
                            "errors": [],
                        }
                    module_uuid = mod.id
                else:
                    logger.warning(
                        "prefetch_next_lessons_task called with no module_id or module_number",
                        user_id=user_id,
                    )
                    return {
                        "status": "skipped",
                        "reason": "no_module",
                        "prefetched": [],
                        "skipped": [],
                        "errors": [],
                    }

                next_units = await _get_next_units(session, module_uuid, current_unit_id)

                logger.info(
                    "Pre-fetching content units",
                    user_id=user_id,
                    units=[uid for uid, _ in next_units],
                )

                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                lesson_service = LessonGenerationService(ClaudeService(), retriever)

                for unit_id_str, content_type in next_units:
                    label = f"{unit_id_str}:{content_type}"
                    try:
                        cached = await _is_cached(
                            session,
                            module_uuid,
                            unit_id_str,
                            content_type,
                            language,
                            level,
                            country,
                        )
                        if cached:
                            skipped.append(label)
                            logger.info(
                                "Skipping already cached content",
                                unit_id=unit_id_str,
                                content_type=content_type,
                                user_id=user_id,
                            )
                            continue

                        if content_type == "lesson":
                            content = await lesson_service.get_or_generate_lesson(
                                module_id=module_uuid,
                                unit_id=unit_id_str,
                                language=language,
                                country=country,
                                level=level,
                                session=session,
                            )
                            prefetched.append(label)
                            logger.info(
                                "Lesson pre-fetched",
                                unit_id=unit_id_str,
                                user_id=user_id,
                            )
                            try:
                                from app.domain.services.lesson_service import (
                                    extract_lesson_text,
                                )

                                c = getattr(content, "content", None)
                                lt = extract_lesson_text(c) if c else ""
                                generate_lesson_audio.apply_async(
                                    kwargs={
                                        "lesson_id": str(content.id),
                                        "module_id": str(module_uuid),
                                        "unit_id": unit_id_str,
                                        "language": language,
                                        "lesson_content": lt[:4000],
                                    },
                                    priority=5,
                                )
                            except Exception as audio_exc:
                                logger.warning(
                                    "Audio dispatch failed (non-fatal)",
                                    unit_id=unit_id_str,
                                    error=str(audio_exc),
                                )

                        elif content_type == "quiz":
                            from app.domain.services.platform_settings_service import (
                                PlatformSettingsService,
                            )
                            from app.domain.services.quiz_service import QuizService

                            settings_svc = PlatformSettingsService()
                            num_questions = int(
                                await settings_svc.get("quiz-unit-questions-count") or 10
                            )
                            quiz_service = QuizService(ClaudeService(), retriever)
                            await quiz_service.get_or_generate_quiz(
                                module_id=module_uuid,
                                unit_id=unit_id_str,
                                language=language,
                                country=country,
                                level=level,
                                num_questions=num_questions,
                                session=session,
                            )
                            prefetched.append(label)
                            logger.info(
                                "Quiz pre-fetched",
                                unit_id=unit_id_str,
                                user_id=user_id,
                            )

                        else:
                            from app.domain.services.lesson_service import (
                                CaseStudyGenerationService,
                            )

                            case_service = CaseStudyGenerationService(ClaudeService(), retriever)
                            await case_service.get_or_generate_case_study(
                                module_id=module_uuid,
                                unit_id=unit_id_str,
                                language=language,
                                country=country,
                                level=level,
                                session=session,
                            )
                            prefetched.append(label)
                            logger.info(
                                "Case study pre-fetched",
                                unit_id=unit_id_str,
                                user_id=user_id,
                            )

                    except Exception as exc:
                        errors.append(label)
                        logger.error(
                            "Failed to pre-fetch content",
                            unit_id=unit_id_str,
                            content_type=content_type,
                            user_id=user_id,
                            error=str(exc),
                        )
        finally:
            await engine.dispose()

        return {
            "status": "complete",
            "prefetched": prefetched,
            "skipped": skipped,
            "errors": errors,
        }

    try:
        result = asyncio.run(_run())
        logger.info(
            "Lesson prefetch completed",
            user_id=user_id,
            module_id=module_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Lesson prefetch task failed",
            user_id=user_id,
            module_id=module_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="1/m",
)
def backfill_missing_image_data(self) -> dict:
    """Re-generate image data for ready images that have NULL binary data (expired Azure URLs).

    Finds all GeneratedImage rows with status='ready' and image_data=NULL,
    then re-downloads and stores binary WebP for each one via the image service.

    Returns:
        dict with counts of processed, succeeded, and failed images
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.models.generated_image import GeneratedImage
    from app.domain.services.image_service import ImageGenerationService, _resize_to_webp
    from app.infrastructure.config.settings import settings

    logger.info("Starting backfill of missing image binary data", task_id=self.request.id)

    async def _run() -> dict:
        set_ai_context("image_generation")  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        processed = 0
        succeeded = 0
        failed = 0

        try:
            async with session_factory() as session:
                result = await session.execute(
                    select(GeneratedImage).where(
                        GeneratedImage.status == "ready",
                        GeneratedImage.image_data.is_(None),
                    )
                )
                images = result.scalars().all()
                logger.info("Found images missing binary data", count=len(images))

                service = ImageGenerationService()
                for img in images:
                    processed += 1
                    try:
                        if not img.concept:
                            logger.warning(
                                "Skipping image with no concept — cannot re-generate",
                                image_id=str(img.id),
                            )
                            failed += 1
                            continue

                        prompt = img.prompt or (
                            f"Educational illustration of {img.concept} "
                            "for West African public health"
                        )
                        image_bytes, _ = await service._call_dalle(prompt)
                        # Keep native width — 512 was far too small and blurred detail.
                        webp_bytes, width = _resize_to_webp(image_bytes)

                        img.image_data = webp_bytes
                        img.image_url = f"/api/v1/images/{img.id}/data"
                        img.width = width
                        img.format = "webp"
                        img.file_size_bytes = len(webp_bytes)
                        await session.flush()
                        succeeded += 1
                        logger.info(
                            "Backfilled image binary data",
                            image_id=str(img.id),
                            size_bytes=len(webp_bytes),
                        )
                    except Exception as exc:
                        failed += 1
                        logger.error(
                            "Failed to backfill image",
                            image_id=str(img.id),
                            error=str(exc),
                        )

                await session.commit()

        finally:
            await engine.dispose()

        return {"processed": processed, "succeeded": succeeded, "failed": failed}

    try:
        result = asyncio.run(_run())
        logger.info(
            "Backfill completed",
            result=result,
            task_id=self.request.id,
        )
        return result
    except Exception as exc:
        logger.error(
            "Backfill task failed",
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"processed": 0, "succeeded": 0, "failed": 0, "error": str(exc)}


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=600,
    time_limit=660,
    rate_limit="2/m",
    priority=5,
)
def pregenerate_on_publish_task(self, course_id: str) -> dict:
    """Pre-generate first 2 content units of Module 01 for a just-published course.

    Iterates over all course languages and generates content for the first 2
    ModuleUnit rows (ordered by order_index) of the module with the lowest
    module_number.  For lesson units, also dispatches TTS audio generation.

    Args:
        course_id: UUID string of the published course.

    Returns:
        dict with lists of generated, skipped, and failed unit/language combos.
    """
    import asyncio

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.claude_service import ClaudeService
    from app.ai.rag.embeddings import EmbeddingService
    from app.ai.rag.retriever import SemanticRetriever
    from app.domain.models.content import GeneratedContent
    from app.domain.models.course import Course
    from app.domain.models.module import Module
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.services.lesson_service import (
        CaseStudyGenerationService,
        LessonGenerationService,
    )
    from app.domain.services.platform_settings_service import PlatformSettingsService
    from app.domain.services.quiz_service import QuizService
    from app.infrastructure.config.settings import settings

    DEFAULT_LEVEL = 1
    UNITS_TO_PRELOAD = 2

    logger.info(
        "pregenerate_on_publish: starting",
        course_id=course_id,
        task_id=self.request.id,
    )

    async def _is_cached(
        session: AsyncSession,
        module_uuid: uuid.UUID,
        unit_id: str,
        content_type: str,
        language: str,
    ) -> bool:
        from app.domain.services._unit_resolution import resolve_module_unit_id

        unit_uuid = await resolve_module_unit_id(session, module_uuid, unit_id)
        cache_query = select(GeneratedContent.id).where(
            GeneratedContent.content_type == content_type,
            GeneratedContent.language == language,
        )
        if unit_uuid is not None:
            cache_query = cache_query.where(GeneratedContent.module_unit_id == unit_uuid)
        else:
            cache_query = cache_query.where(
                GeneratedContent.module_id == module_uuid,
                GeneratedContent.module_unit_id.is_(None),
                GeneratedContent.content["unit_id"].astext == unit_id,
            )
        result = await session.execute(cache_query)
        return result.scalar_one_or_none() is not None

    async def _run() -> dict:
        set_ai_context("lesson_generation", course_id=_safe_uuid(course_id))  # ledger (#2629)
        engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=2)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        generated: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        try:
            async with session_factory() as session:
                course_result = await session.execute(
                    select(Course).where(Course.id == uuid.UUID(course_id))
                )
                course = course_result.scalar_one_or_none()
                if not course:
                    logger.warning("pregenerate_on_publish: course not found", course_id=course_id)
                    return {
                        "generated": [],
                        "skipped": [],
                        "failed": [],
                        "reason": "course_not_found",
                    }

                languages = [
                    lang.strip()
                    for lang in (course.languages or "fr,en").split(",")
                    if lang.strip()
                ]

                settings_svc = PlatformSettingsService()
                default_country = await settings_svc.get("content-preload-default-country") or "CI"
                quiz_questions_count = int(
                    await settings_svc.get("quiz-unit-questions-count") or 10
                )

                module_result = await session.execute(
                    select(Module)
                    .where(Module.course_id == uuid.UUID(course_id))
                    .order_by(Module.module_number)
                    .limit(1)
                )
                module = module_result.scalar_one_or_none()
                if not module:
                    logger.warning(
                        "pregenerate_on_publish: no module found for course",
                        course_id=course_id,
                    )
                    return {"generated": [], "skipped": [], "failed": [], "reason": "no_module"}

                units_result = await session.execute(
                    select(ModuleUnit)
                    .where(ModuleUnit.module_id == module.id)
                    .order_by(ModuleUnit.order_index)
                    .limit(UNITS_TO_PRELOAD)
                )
                units = list(units_result.scalars().all())

                if not units:
                    logger.warning(
                        "pregenerate_on_publish: no units found in module",
                        course_id=course_id,
                        module_id=str(module.id),
                    )
                    return {"generated": [], "skipped": [], "failed": [], "reason": "no_units"}

                embedding_service = EmbeddingService(
                    api_key=settings.openai_api_key, model=settings.embedding_model
                )
                retriever = SemanticRetriever(embedding_service)
                lesson_service = LessonGenerationService(ClaudeService(), retriever)
                quiz_service = QuizService(ClaudeService(), retriever)
                case_study_service = CaseStudyGenerationService(ClaudeService(), retriever)

                for unit in units:
                    unit_id = unit.unit_number  # canonical "1.1" format (#1898)
                    raw_type = (unit.unit_type or "").lower().replace("-", "_").replace(" ", "_")
                    if "quiz" in raw_type or "evaluation" in raw_type or "évaluation" in raw_type:
                        content_type = "quiz"
                    elif "case" in raw_type or "etude" in raw_type or "étude" in raw_type:
                        content_type = "case_study"
                    else:
                        content_type = "lesson"

                    for language in languages:
                        label = f"{unit_id}:{content_type}:{language}"
                        try:
                            cached = await _is_cached(
                                session, module.id, unit_id, content_type, language
                            )
                            if cached:
                                skipped.append(label)
                                logger.info(
                                    "pregenerate_on_publish: cache hit — skipping",
                                    label=label,
                                )
                                continue

                            if content_type == "lesson":
                                content = await lesson_service.get_or_generate_lesson(
                                    module_id=module.id,
                                    unit_id=unit_id,
                                    language=language,
                                    country=default_country,
                                    level=DEFAULT_LEVEL,
                                    session=session,
                                )
                                generated.append(label)
                                logger.info(
                                    "pregenerate_on_publish: lesson generated",
                                    label=label,
                                    content_id=str(content.id),
                                )
                                from app.domain.services.lesson_service import (
                                    extract_lesson_text,
                                )

                                c = getattr(content, "content", None)
                                lt = extract_lesson_text(c) if c else ""
                                generate_lesson_audio.apply_async(
                                    kwargs={
                                        "lesson_id": str(content.id),
                                        "module_id": str(module.id),
                                        "unit_id": unit_id,
                                        "language": language,
                                        "lesson_content": lt[:4000],
                                    },
                                    priority=5,
                                )

                            elif content_type == "quiz":
                                content = await quiz_service.get_or_generate_quiz(
                                    module_id=module.id,
                                    unit_id=unit_id,
                                    language=language,
                                    country=default_country,
                                    level=DEFAULT_LEVEL,
                                    num_questions=quiz_questions_count,
                                    session=session,
                                )
                                generated.append(label)
                                logger.info(
                                    "pregenerate_on_publish: quiz generated",
                                    label=label,
                                    content_id=str(content.id),
                                )

                            else:
                                content = await case_study_service.get_or_generate_case_study(
                                    module_id=module.id,
                                    unit_id=unit_id,
                                    language=language,
                                    country=default_country,
                                    level=DEFAULT_LEVEL,
                                    session=session,
                                )
                                generated.append(label)
                                logger.info(
                                    "pregenerate_on_publish: case study generated",
                                    label=label,
                                    content_id=str(content.id),
                                )

                        except Exception as exc:
                            failed.append(label)
                            logger.error(
                                "pregenerate_on_publish: generation failed",
                                label=label,
                                error=str(exc),
                            )

            # Auto-trigger a full course quality sweep now that the first
            # units are generated. Best-effort — never block the publish.
            try:
                from app.domain.services.quality_agent_service import CourseQualityService
                from app.tasks.quality_assessment import assess_course_task

                async with session_factory() as qa_session:
                    svc = CourseQualityService(ClaudeService(), semantic_retriever=None)
                    run = await svc.assess_course(
                        course_id=uuid.UUID(course_id),
                        triggered_by_user_id=None,
                        session=qa_session,
                        run_kind="full",
                    )
                    await qa_session.commit()
                if run.status == "queued":
                    assess_course_task.apply_async(
                        kwargs={"run_id": str(run.id)},
                        priority=4,
                        countdown=30,
                    )
                    logger.info(
                        "pregenerate_on_publish: auto quality sweep dispatched",
                        course_id=course_id,
                        run_id=str(run.id),
                    )
            except Exception as _exc:
                logger.warning(
                    "pregenerate_on_publish: auto quality sweep dispatch failed (non-fatal)",
                    course_id=course_id,
                    error=str(_exc),
                )

        finally:
            await engine.dispose()

        return {"generated": generated, "skipped": skipped, "failed": failed}

    try:
        result = asyncio.run(_run())
        logger.info(
            "pregenerate_on_publish: completed",
            course_id=course_id,
            result=result,
            task_id=self.request.id,
        )
        # The quality block inside _run() only fires when generation reaches the
        # end of the loop.  Early returns ("no_module", "no_units") bypass it.
        # Backstop: fire quality here too when real content exists — the service's
        # day-bucketed idempotency key collapses both triggers to one run (#2358).
        if not result.get("reason"):
            try:
                from sqlalchemy.ext.asyncio import (
                    AsyncSession,
                    async_sessionmaker,
                    create_async_engine,
                )

                from app.ai.claude_service import ClaudeService as _ClaudeService
                from app.domain.services.quality_agent_service import (
                    CourseQualityService as _CourseQualityService,
                )
                from app.infrastructure.config.settings import settings as _cfg
                from app.tasks.quality_assessment import assess_course_task

                async def _trigger_quality() -> None:
                    _engine = create_async_engine(
                        _cfg.database_url, echo=False, pool_size=2, max_overflow=1
                    )
                    _sf = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
                    try:
                        async with _sf() as qa_session:
                            svc = _CourseQualityService(_ClaudeService(), semantic_retriever=None)
                            run = await svc.assess_course(
                                course_id=uuid.UUID(course_id),
                                triggered_by_user_id=None,
                                session=qa_session,
                                run_kind="full",
                            )
                            await qa_session.commit()
                        if run.status == "queued":
                            assess_course_task.apply_async(
                                kwargs={"run_id": str(run.id)},
                                priority=4,
                                countdown=30,
                            )
                            logger.info(
                                "pregenerate_on_publish: backstop quality sweep dispatched",
                                course_id=course_id,
                                run_id=str(run.id),
                            )
                    finally:
                        await _engine.dispose()

                asyncio.run(_trigger_quality())
            except Exception as _exc:
                logger.warning(
                    "pregenerate_on_publish: backstop quality dispatch failed (non-fatal)",
                    course_id=course_id,
                    error=str(_exc),
                )
        return result
    except Exception as exc:
        logger.error(
            "pregenerate_on_publish: task failed",
            course_id=course_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"generated": [], "skipped": [], "failed": [], "error": str(exc)}


# ``generate_media_summary`` was removed in #1802. The per-module
# audio summary never actually worked and the per-module video
# summary was replaced with the per-lesson HeyGen path
# (``generate_lesson_video``). See issue #1802 for the full rescope.
