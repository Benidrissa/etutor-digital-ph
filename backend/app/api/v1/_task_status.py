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
_OWNER_PREFIX = "content_task_owner:"
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


def dispatch_markers(
    task_id: str, owner_key: str | None = None, owner_ttl_s: int | None = None
) -> list[tuple[str, int, str]]:
    """``(key, ttl, value)`` of what :func:`mark_dispatched` and :func:`vouch_while_owned` write.

    For a dispatcher without the async client (a Celery task dispatching its
    own continuation): it writes these with ``SETEX`` before ``apply_async``.
    """
    if not task_id:
        return []
    markers = [(_key(task_id), _TTL_SECONDS, datetime.now(tz=UTC).isoformat())]
    if owner_key and owner_ttl_s:
        markers.append((f"{_OWNER_PREFIX}{task_id}", owner_ttl_s, owner_key))
    return markers


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


async def vouch_while_owned(task_id: str, owner_key: str, ttl_s: int) -> None:
    """Report ``task_id`` as queued, never stalled, while ``owner_key`` names it.

    For a task that may legitimately wait in the queue longer than
    :data:`TASK_STALL_THRESHOLD_S` — a rate-limited story generation that
    concurrent requests join through a dedup key. The dispatcher writes this
    before claiming ``owner_key`` (a Redis key whose value is the task id, with
    its own TTL, released when the task ends). While that key still holds the
    task id, the task is alive as far as the dispatcher is concerned, and the
    status endpoint must agree with it: a PENDING state then means "queued".
    Best effort: without Redis the plain stall rules apply.
    """
    if not task_id or not owner_key:
        return
    try:
        await redis_client.setex(f"{_OWNER_PREFIX}{task_id}", ttl_s, owner_key)
    except Exception as exc:
        logger.warning("task_status.vouch_failed", task_id=task_id, error=str(exc))


async def is_vouched(task_id: str) -> bool:
    """Whether a dedup key still names ``task_id`` (see :func:`vouch_while_owned`)."""
    if not task_id:
        return False
    try:
        owner_key = await redis_client.get(f"{_OWNER_PREFIX}{task_id}")
        if not owner_key:
            return False
        return await redis_client.get(owner_key) == task_id
    except Exception as exc:
        logger.warning("task_status.is_vouched_failed", task_id=task_id, error=str(exc))
        return False
