"""Celery task drawing a course's story-mode art (#2675).

Dispatched by the story routes (``GET /story-courses/module/{module_id}`` and
``GET /story-courses/{slug}``) when the story they serve has looks whose art is
missing or stale, deduplicated with one Redis key per course: one run per
course at a time. See :mod:`app.domain.services.story_art_service`.
"""

from __future__ import annotations

import uuid

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

#: Connections: one per image write in flight (CONCURRENCY) plus the reads.
STORY_ART_POOL_SIZE = 4
STORY_ART_MAX_OVERFLOW = 2


def story_art_dispatch_key(course_id: uuid.UUID | str) -> str:
    """Redis key holding the id of the task drawing a course's story art."""
    return f"story_art_dispatch:course:{course_id}"


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

    One run per course: the task holds the course's Redis key (``dedup_key``,
    the API's key, or the same key for an operator's run) for its whole run,
    and returns ``{"status": "skipped"}`` without drawing anything when
    another task holds it. The key is released when the task ends, however it
    ends. Without Redis the run goes ahead. Never retried by Celery: a retry
    would pay for the images again.
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
        try:
            model = SettingsCache.instance().get("ai-model-image", DEFAULT_IMAGE_MODEL)
            generator = StoryArtGenerator(session_factory, model=model, retry_failed=retry_failed)
            return await generator.run(uuid.UUID(course_id))
        finally:
            await _await_other_tasks(20.0)
            await engine.dispose()

    key = dedup_key or story_art_dispatch_key(course_id)
    try:
        if _hold_story_dispatch(key, self.request.id, STORY_ART_DISPATCH_TTL_S) == 0:
            # The course's key names another task (this one waited in the queue
            # past the key's TTL and a later view dispatched again, or the
            # broker redelivered it): that run draws; two would pay twice.
            logger.warning(
                "Story art run skipped: another run holds the course",
                course_id=course_id,
                task_id=self.request.id,
            )
            return {"status": "skipped", "reason": "another_run_holds_course"}
        result = asyncio.run(_run())
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
        # A compare-and-delete on this task's id: a key another task holds is
        # left alone (the skipped case above included).
        _release_story_dispatch(key, self.request.id)
