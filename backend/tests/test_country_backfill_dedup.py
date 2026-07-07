"""Tests for the country-fallback backfill dedup guard (#2581).

A country-fallback is served on every view of a unit lacking the learner's
country, so without a guard each page view enqueues another backfill for the
same content while the first is still running. The guard lets only the first
view within the TTL window enqueue a job.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.infrastructure.cache import backfill_dedup


@pytest.mark.asyncio
async def test_first_view_dispatches_repeat_view_suppressed():
    """Redis SET NX returns truthy on first acquire, falsy while key lives."""
    unit_id = uuid.uuid4()
    fake_redis = AsyncMock()
    # First SET NX succeeds (key absent), second returns None (key present).
    fake_redis.set = AsyncMock(side_effect=[True, None])

    with patch("app.infrastructure.cache.redis.redis_client", fake_redis):
        first = await backfill_dedup.should_dispatch_country_backfill(
            unit_id, "lesson", "fr", 1, "CI"
        )
        second = await backfill_dedup.should_dispatch_country_backfill(
            unit_id, "lesson", "fr", 1, "CI"
        )

    assert first is True
    assert second is False
    # Guard uses NX + TTL so it self-expires and re-arms.
    _, kwargs = fake_redis.set.call_args
    assert kwargs.get("nx") is True
    assert kwargs.get("ex") == backfill_dedup._COUNTRY_BACKFILL_DEDUP_TTL


@pytest.mark.asyncio
async def test_fails_open_when_redis_unavailable():
    """Redis errors must not block backfill — the task is idempotent anyway."""
    fake_redis = AsyncMock()
    fake_redis.set = AsyncMock(side_effect=ConnectionError("redis down"))

    with patch("app.infrastructure.cache.redis.redis_client", fake_redis):
        result = await backfill_dedup.should_dispatch_country_backfill(
            uuid.uuid4(), "quiz", "en", 2, "NG"
        )

    assert result is True
