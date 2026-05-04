"""Tests for GET /api/v1/content/status/{task_id}.

Covers the dispatch-marker logic that disambiguates Celery's "PENDING"
state between (a) queued waiting for a worker, (b) worker outage / unknown
task ID (``task_lost``), and (c) marker-present-but-old (``task_stalled``).
Without this disambiguation the unit page silently spins for the full
3-minute frontend timeout when Celery is unhealthy.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import content as content_module


@pytest.mark.asyncio
async def test_pending_with_no_marker_returns_task_lost():
    """PENDING + no Redis marker => task we never knew about (failed:task_lost)."""
    fake_async_result = MagicMock()
    fake_async_result.state = "PENDING"

    with (
        patch.object(content_module, "AsyncResult", return_value=fake_async_result),
        patch.object(content_module, "task_dispatched_at", AsyncMock(return_value=None)),
    ):
        response = await content_module.get_generation_status("missing-task-id")

    body = response.body.decode()
    assert response.status_code == 200
    assert '"failed"' in body
    assert "task_lost" in body


@pytest.mark.asyncio
async def test_pending_with_recent_marker_returns_pending():
    """PENDING + recent marker => task is queued, keep polling."""
    fake_async_result = MagicMock()
    fake_async_result.state = "PENDING"
    recent = datetime.now(tz=UTC) - timedelta(seconds=5)

    with (
        patch.object(content_module, "AsyncResult", return_value=fake_async_result),
        patch.object(content_module, "task_dispatched_at", AsyncMock(return_value=recent)),
    ):
        response = await content_module.get_generation_status("queued-task-id")

    assert response.status_code == 200
    assert '"pending"' in response.body.decode()


@pytest.mark.asyncio
async def test_pending_with_old_marker_returns_task_stalled():
    """PENDING + marker older than threshold => no worker picked it up."""
    fake_async_result = MagicMock()
    fake_async_result.state = "PENDING"
    stale = datetime.now(tz=UTC) - timedelta(seconds=content_module.TASK_STALL_THRESHOLD_S + 5)

    with (
        patch.object(content_module, "AsyncResult", return_value=fake_async_result),
        patch.object(content_module, "task_dispatched_at", AsyncMock(return_value=stale)),
    ):
        response = await content_module.get_generation_status("stalled-task-id")

    body = response.body.decode()
    assert response.status_code == 200
    assert '"failed"' in body
    assert "task_stalled" in body


@pytest.mark.asyncio
async def test_started_returns_generating():
    """STARTED state (now reliable thanks to task_track_started) => generating."""
    fake_async_result = MagicMock()
    fake_async_result.state = "STARTED"

    with patch.object(content_module, "AsyncResult", return_value=fake_async_result):
        response = await content_module.get_generation_status("running-task-id")

    assert '"generating"' in response.body.decode()


@pytest.mark.asyncio
async def test_success_with_failed_payload_surfaces_error():
    """Tasks return SUCCESS with {status: failed, error: ...} on caught exceptions."""
    fake_async_result = MagicMock()
    fake_async_result.state = "SUCCESS"
    fake_async_result.result = {"status": "failed", "error": "No relevant content found"}

    with patch.object(content_module, "AsyncResult", return_value=fake_async_result):
        response = await content_module.get_generation_status("failed-task-id")

    body = response.body.decode()
    assert '"failed"' in body
    assert "No relevant content found" in body


@pytest.mark.asyncio
async def test_success_with_content_id_returns_complete():
    fake_async_result = MagicMock()
    fake_async_result.state = "SUCCESS"
    fake_async_result.result = {"content_id": "abc-123"}

    with patch.object(content_module, "AsyncResult", return_value=fake_async_result):
        response = await content_module.get_generation_status("done-task-id")

    body = response.body.decode()
    assert '"complete"' in body
    assert "abc-123" in body
