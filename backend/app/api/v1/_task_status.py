"""Dispatch markers for content-generation Celery tasks.

Without a marker we cannot tell `AsyncResult.state == "PENDING"` apart for
two very different situations:

* the task is queued and a worker hasn't picked it up yet, and
* the task ID is unknown to Celery (worker outage, expired result,
  client typo) — Celery returns ``"PENDING"`` here too.

Both used to render as `{status: "pending"}` from `/content/status`,
which left the lesson viewer polling for the full 3-minute frontend
timeout before giving up. We persist a tiny dispatch marker in Redis so
the status endpoint can distinguish ``task_lost`` from queued, and
``task_stalled`` from in-flight, and surface a real error to the user
within the first poll cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.infrastructure.cache.redis import redis_client

logger = structlog.get_logger(__name__)

_KEY_PREFIX = "content_task:"
_TTL_SECONDS = 3600  # match celery_app.conf.result_expires
TASK_STALL_THRESHOLD_S = 30


def _key(task_id: str) -> str:
    return f"{_KEY_PREFIX}{task_id}"


async def mark_dispatched(task_id: str) -> None:
    if not task_id:
        return
    now_iso = datetime.now(tz=UTC).isoformat()
    try:
        await redis_client.setex(_key(task_id), _TTL_SECONDS, now_iso)
    except Exception as exc:
        logger.warning("task_status.mark_dispatched_failed", task_id=task_id, error=str(exc))


async def dispatched_at(task_id: str) -> datetime | None:
    if not task_id:
        return None
    try:
        raw = await redis_client.get(_key(task_id))
    except Exception as exc:
        logger.warning("task_status.dispatched_at_failed", task_id=task_id, error=str(exc))
        return None
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
