"""Celery task drawing a course's story-mode art (#2675).

Dispatched by the story routes (``GET /story-courses/module/{module_id}`` and
``GET /story-courses/{slug}``) when the course's art has something to draw,
deduplicated with one Redis key per course. The task itself enforces one run
per course with a PostgreSQL advisory lock. See
:mod:`app.domain.services.story_art_service`.
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import AsyncIterator

import sqlalchemy as sa
import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.ai.usage_context import set_ai_context
from app.tasks.celery_app import celery_app
from app.tasks.content_generation import (
    CallbackTask,
    _await_other_tasks,
    _hold_story_dispatch,
    _release_story_dispatch,
    _safe_uuid,
)

logger = structlog.get_logger(__name__)

#: A run's worst case: about 26 images (at most MAX_IMAGES_PER_RUN, 40), three
#: in flight at a time, each at most two attempts with the SDK's own retries
#: off: a generation times out at 120 s, a high-fidelity edit at 210 s, and a
#: rate-limited first attempt waits up to 60 s before the second. A
#: character's poses wait for its idle, so one character takes at most about
#: 300 + 480 s. Usual runs take a few minutes. Every image is stored as soon as
#: it is drawn, so a run cut short keeps its work and the next view starts a
#: run for the rest.
STORY_ART_SOFT_LIMIT = 2400
STORY_ART_HARD_LIMIT = 2460

#: The API's dedup key for a course's art run lives this long (claimed at
#: dispatch, armed again when the task starts). It stays under the broker's
#: 3600 s visibility timeout, like the story keys.
STORY_ART_DISPATCH_TTL_S = STORY_ART_HARD_LIMIT + 60

#: Connections: the course lock's own, one per image write in flight
#: (CONCURRENCY), plus the reads.
STORY_ART_POOL_SIZE = 5
STORY_ART_MAX_OVERFLOW = 2

#: Reported by a run that found another run of the course holding its lock.
SKIPPED_LOCKED = {"status": "skipped", "reason": "course_run_in_progress"}


def story_art_dispatch_key(course_id: uuid.UUID | str) -> str:
    """Redis key holding the id of the task drawing a course's story art."""
    return f"story_art_dispatch:course:{course_id}"


def story_art_lock_key(course_id: uuid.UUID) -> int:
    """The course's advisory-lock key: a stable signed 64-bit integer."""
    digest = hashlib.sha256(b"story_art:" + course_id.bytes).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@contextlib.asynccontextmanager
async def course_run_lock(engine, course_id: uuid.UUID) -> AsyncIterator[bool]:
    """Hold the course's PostgreSQL advisory lock for a run; yields whether it was taken.

    ``pg_try_advisory_lock`` on a connection of its own, kept for the whole
    run and in autocommit (no transaction stays open), then unlocked. The
    lock is the database's, so it holds whatever Redis says: a broker
    redelivery of the same task id, or a run started after the dispatch key
    expired, finds it taken. A connection that dies frees it, and the task's
    engine is disposed after every run, which closes this connection.
    """
    key = story_art_lock_key(course_id)
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        taken = bool(
            (await connection.execute(sa.select(sa.func.pg_try_advisory_lock(key)))).scalar()
        )
        try:
            yield taken
        finally:
            if taken:
                with contextlib.suppress(Exception):
                    await connection.execute(sa.select(sa.func.pg_advisory_unlock(key)))


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=STORY_ART_SOFT_LIMIT,
    time_limit=STORY_ART_HARD_LIMIT,
    rate_limit="5/m",
)
def generate_story_art(
    self,
    course_id: str,
    dedup_key: str | None = None,
    retry_failed: bool = False,
) -> dict:
    """Draw the course's missing or stale story art: character poses and backdrops.

    Uses the ``ai-model-image`` setting; transparent character renders and pose
    edits go to gpt-image-1 when that model cannot do them. Images already
    ready for their current look are skipped; a run draws at most
    ``MAX_IMAGES_PER_RUN`` images and logs what it skipped. A failed image is
    retried once, then stored as ``failed``: a deterministic failure is not
    tried again until its look changes (unless ``retry_failed``, for
    operators); a transient one (outage, quota, timeout) is tried again by a
    later run after a backoff.

    One run per course, in two layers, each returning ``{"status": "skipped"}``
    before anything is drawn:

    * the course's Redis key (``dedup_key``, the API's key, or the same key
      for an operator's run), re-armed for the run: skipped when another task
      id holds it. Without Redis the run goes ahead to the next layer;
    * the course's PostgreSQL advisory lock (:func:`course_run_lock`), held
      for the whole run: skipped when another run holds it. This one also
      catches a broker redelivery of the *same* task id (``acks_late``),
      which the Redis key, naming that id, lets through.

    The key is released when the task ends (a compare-and-delete on its own
    id), except by a copy the lock turned away, whose id the running copy
    still holds. Never retried by Celery: a retry would pay for the images
    again.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.ai.providers.image_provider import DEFAULT_IMAGE_MODEL
    from app.domain.services.platform_settings_service import SettingsCache
    from app.domain.services.story_art_service import FEATURE_STORY_ART, StoryArtGenerator
    from app.infrastructure.config.settings import settings

    logger.info("Starting story art generation", course_id=course_id, task_id=self.request.id)

    async def _run() -> dict:
        set_ai_context(FEATURE_STORY_ART, course_id=_safe_uuid(course_id))  # ledger
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_size=STORY_ART_POOL_SIZE,
            max_overflow=STORY_ART_MAX_OVERFLOW,
        )
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        course_uuid = uuid.UUID(course_id)
        try:
            async with course_run_lock(engine, course_uuid) as taken:
                if not taken:
                    logger.warning(
                        "Story art run skipped: another run holds the course lock",
                        course_id=course_id,
                        task_id=self.request.id,
                    )
                    return dict(SKIPPED_LOCKED)
                model = SettingsCache.instance().get("ai-model-image", DEFAULT_IMAGE_MODEL)
                generator = StoryArtGenerator(
                    session_factory, model=model, retry_failed=retry_failed
                )
                return await generator.run(course_uuid)
        finally:
            await _await_other_tasks(20.0)
            await engine.dispose()

    key = dedup_key or story_art_dispatch_key(course_id)
    release_key = True
    try:
        if _hold_story_dispatch(key, self.request.id, STORY_ART_DISPATCH_TTL_S) == 0:
            # The course's key names another task id: this one waited in the
            # queue past the key's TTL and a later view dispatched again. That
            # run draws; two would pay twice. (A redelivery of this same id
            # passes here: the advisory lock in _run turns it away.)
            logger.warning(
                "Story art run skipped: another run holds the course",
                course_id=course_id,
                task_id=self.request.id,
            )
            return {"status": "skipped", "reason": "another_run_holds_course"}
        result = asyncio.run(_run())
        if result == SKIPPED_LOCKED:
            # The running copy may have this very id: leave its key alone.
            release_key = False
        logger.info(
            "Story art generation completed",
            course_id=course_id,
            result=result,
            task_id=self.request.id,
        )
        return result
    except SoftTimeLimitExceeded:
        logger.warning(
            "Story art generation hit its soft time limit; the images drawn are kept",
            course_id=course_id,
            task_id=self.request.id,
        )
        return {"status": "failed", "error": "time_limit_exceeded"}
    except Exception as exc:
        logger.error(
            "Story art generation failed",
            course_id=course_id,
            exception=str(exc),
            task_id=self.request.id,
        )
        return {"status": "failed", "error": str(exc)}
    finally:
        # A compare-and-delete on this task's id: a key another task id holds
        # is left alone (the first skipped case included).
        if release_key:
            _release_story_dispatch(key, self.request.id)
