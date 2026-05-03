"""Tests for GET /api/v1/video/lesson/{lesson_id} (#2130).

Asserts the endpoint distinguishes "lesson does not exist" (404) from
"lesson exists but no video generated yet" (200 with empty list). The
former keeps the original semantics; the latter previously also returned
404 and surfaced as a console error on every lesson page load.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.main import app


@pytest.fixture
def override_user():
    user = AuthenticatedUser(
        {
            "sub": str(uuid.uuid4()),
            "email": "learner@example.com",
            "role": "user",
            "preferred_language": "fr",
            "current_level": 1,
        }
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)


def _make_lesson_row(language: str = "fr") -> MagicMock:
    row = MagicMock()
    row.module_id = uuid.uuid4()
    row.unit_id = "1.1"
    row.language = language
    return row


def _override_db(*, lesson_meta, video_rows):
    """Build a mock DB whose two execute() calls return the lesson lookup
    then the video lookup.
    """
    lesson_first = MagicMock()
    lesson_first.first = MagicMock(return_value=lesson_meta)
    video_scalars = MagicMock()
    video_scalars.all = MagicMock(return_value=video_rows)
    video_result = MagicMock()
    video_result.scalars = MagicMock(return_value=video_scalars)

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[lesson_first, video_result])
    app.dependency_overrides[get_db_session] = lambda: mock_db
    return mock_db


async def test_lesson_not_found_returns_404(override_user) -> None:
    _override_db(lesson_meta=None, video_rows=[])
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/video/lesson/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "lesson_not_found"
    finally:
        app.dependency_overrides.pop(get_db_session, None)


async def test_lesson_with_no_video_returns_200_empty_list(override_user) -> None:
    """The fix for #2130: previously this returned 404 and polluted the
    browser console on every lesson page load. Now returns 200 with an
    empty `video` list so the FE can render the Generate button without
    a network error.
    """
    _override_db(lesson_meta=_make_lesson_row(), video_rows=[])
    lesson_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/video/lesson/{lesson_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["lesson_id"] == str(lesson_id)
        assert body["video"] == []
        assert body["total"] == 0
    finally:
        app.dependency_overrides.pop(get_db_session, None)


async def test_lesson_with_video_returns_video_list(override_user) -> None:
    video_row = MagicMock()
    video_row.id = uuid.uuid4()
    video_row.status = "ready"
    video_row.duration_seconds = 90
    video_row.file_size_bytes = 12345
    _override_db(lesson_meta=_make_lesson_row(), video_rows=[video_row])
    lesson_id = uuid.uuid4()
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"/api/v1/video/lesson/{lesson_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        first = body["video"][0]
        assert first["status"] == "ready"
        assert first["duration_seconds"] == 90
        assert first["video_url"] == f"/api/v1/video/{video_row.id}/data"
    finally:
        app.dependency_overrides.pop(get_db_session, None)
