"""Redis dedup guard for country-fallback backfill dispatch.

A country-fallback is served on *every* view of a unit that lacks the learner's
country. Without a guard, each page view (and each prefetch) would enqueue
another ``generate_country_content_task`` for the same content key while the
first is still running. This short-TTL guard lets only the first view within
the window enqueue a backfill.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

# Long enough to cover a generation plus its retries; short enough to re-arm if
# that truly failed and the row is still missing on a later view.
_COUNTRY_BACKFILL_DEDUP_TTL = 300


async def should_dispatch_country_backfill(
    module_unit_id,
    content_type: str,
    language: str,
    level: int,
    country: str,
) -> bool:
    """Return True only for the first fallback view of a given content key within
    the TTL window. Fails open (dispatch) if Redis is unavailable — the backfill
    task is idempotent (it skips when the row already exists)."""
    try:
        from app.infrastructure.cache.redis import redis_client

        key = f"country_backfill:{module_unit_id}:{content_type}:{language}:{level}:{country}"
        acquired = await redis_client.set(key, "1", nx=True, ex=_COUNTRY_BACKFILL_DEDUP_TTL)
        return bool(acquired)
    except Exception as exc:
        logger.warning("country_backfill dedup check failed (dispatching)", error=str(exc))
        return True
