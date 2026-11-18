"""Celery task matching story prop phrases against the shared library (Phase A).

Dispatched by the story routes when a served document has search phrases
with no cached result (:func:`app.api.v1.story_courses.dispatch_story_props_resolution`),
deduplicated with one Redis key per set of phrases. It embeds the phrases
once, matches them (:func:`app.domain.services.story_prop_library.resolve_phrases`)
and stores every result, a match or a miss, so the next view serves it. With
an empty library nothing is embedded. Cheap and idempotent: running twice
writes the same rows.
"""

from __future__ import annotations

import hashlib

import structlog
from celery.exceptions import SoftTimeLimitExceeded

from app.ai.usage_context import set_ai_context
from app.tasks.celery_app import celery_app
from app.tasks.content_generation import (
    CallbackTask,
    _await_other_tasks,
    _hold_story_dispatch,
    _release_story_dispatch,
)

logger = structlog.get_logger(__name__)

#: One embedding call and a few small writes.
STORY_PROPS_SOFT_LIMIT = 120
STORY_PROPS_HARD_LIMIT = 150
STORY_PROPS_DISPATCH_TTL_S = STORY_PROPS_HARD_LIMIT + 60


def story_props_dispatch_key(keys: list[list[str]] | list[tuple[str, str]]) -> str:
    """Redis key of the task matching this set of phrases (order does not matter)."""
    canonical = "\n".join(sorted(f"{kind}\t{phrase}" for phrase, kind in keys))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"story_props_dispatch:{digest}"


def _embedder():
    """The RAG embedding service's batch call, or None without an OpenAI key."""
    from app.ai.rag.embeddings import EmbeddingService
    from app.infrastructure.config.settings import settings

    if not settings.openai_api_key:
        return None
    try:
        return EmbeddingService(api_key=settings.openai_api_key).generate_embeddings_batch
    except Exception as exc:  # the tokenizer download, for one
        logger.warning("Story prop embeddings unavailable", error=str(exc))
        return None


@celery_app.task(
    bind=True,
    base=CallbackTask,
    soft_time_limit=STORY_PROPS_SOFT_LIMIT,
    time_limit=STORY_PROPS_HARD_LIMIT,
)
def resolve_story_props(self, keys: list[list[str]], dedup_key: str | None = None) -> dict:
    """Match ``keys`` (``[phrase, prop kind]`` pairs) and cache every result."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.domain.services.story_prop_library import FEATURE_STORY_PROPS, resolve_phrases
    from app.infrastructure.config.settings import settings

    pairs = [
        (str(pair[0]), str(pair[1]))
        for pair in keys
        if isinstance(pair, list | tuple) and len(pair) == 2
    ]

    async def _run() -> dict:
        set_ai_context(FEATURE_STORY_PROPS)  # ledger
        engine = create_async_engine(settings.database_url, echo=False, pool_size=2, max_overflow=0)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            async with session_factory() as session:
                results = await resolve_phrases(session, pairs, _embedder())
                await session.commit()
            return {
                "status": "ok",
                "phrases": len(results),
                "matched": sum(1 for match in results.values() if match.asset_id),
            }
        finally:
            await _await_other_tasks(20.0)
            await engine.dispose()

    key = dedup_key or story_props_dispatch_key(pairs)
    try:
        if _hold_story_dispatch(key, self.request.id, STORY_PROPS_DISPATCH_TTL_S) == 0:
            return {"status": "skipped", "reason": "another_run_holds_phrases"}
        result = asyncio.run(_run())
        logger.info("Story prop phrases resolved", result=result, task_id=self.request.id)
        return result
    except SoftTimeLimitExceeded:
        logger.warning("Story prop resolution hit its soft time limit", task_id=self.request.id)
        return {"status": "failed", "error": "time_limit_exceeded"}
    except Exception as exc:
        logger.error("Story prop resolution failed", exception=str(exc), task_id=self.request.id)
        return {"status": "failed", "error": str(exc)}
    finally:
        _release_story_dispatch(key, self.request.id)
