"""API tests for the story-course endpoints.

These cover the paths that need no database: the authoring loop (`/validate`),
the refusal to publish an invalid week, malformed-file handling and auth. The
list/detail/upsert paths need a live Postgres and are covered by the
integration fixtures in conftest.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.story_courses import _ADMIN
from app.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "story_course_w04.json"
TIMES = "×"


@pytest.fixture(scope="module")
def raw_course() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def course(raw_course: dict) -> dict:
    return copy.deepcopy(raw_course)


def _admin_user() -> AuthenticatedUser:
    return AuthenticatedUser(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "admin@example.com",
            "role": "admin",
        }
    )


@pytest.fixture
async def admin_client() -> AsyncClient:
    """Client authenticated as an admin, with the DB dependency stubbed.

    The endpoints exercised here never read from the session, so an object that
    would error on use is the right stub: if a test starts touching the DB, it
    fails loudly rather than silently passing against a half-real session.
    """

    async def no_db():
        yield object()

    app.dependency_overrides[_ADMIN] = _admin_user
    app.dependency_overrides[get_current_user] = _admin_user
    app.dependency_overrides[get_db] = no_db
    app.dependency_overrides[get_db_session] = no_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def anon_client() -> AsyncClient:
    app.dependency_overrides.clear()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestValidateEndpoint:
    """POST /api/v1/story-courses/validate — the authoring loop."""

    async def test_valid_course_reports_ok(self, admin_client, course):
        resp = await admin_client.post("/api/v1/story-courses/validate", json={"content": course})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["errors"] == []
        assert body["checks"]["max_points"] == 29

    async def test_invalid_course_reports_paths(self, admin_client, course):
        """An author needs the code and the path, not just a boolean."""
        next(q for q in course["questions"] if q["id"] == "q3")["answer"] = (
            f"2² {TIMES} 3² {TIMES} 5"
        )
        resp = await admin_client.post("/api/v1/story-courses/validate", json={"content": course})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        mismatch = next(e for e in body["errors"] if e["code"] == "answer_mismatch")
        assert mismatch["path"] == "questions[q3].answer"
        assert mismatch["severity"] == "error"

    async def test_malformed_file_is_422(self, admin_client):
        resp = await admin_client.post(
            "/api/v1/story-courses/validate",
            json={"content": {"format": "story-course/1", "week": "not a number"}},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["error"] == "malformed_course_file"

    async def test_wrong_format_version_is_422(self, admin_client, course):
        course["format"] = "story-course/2"
        resp = await admin_client.post("/api/v1/story-courses/validate", json={"content": course})
        assert resp.status_code == 422


class TestPublishRefusal:
    """An invalid week must never reach learners."""

    async def test_publishing_invalid_course_is_409(self, admin_client, course):
        course["tutor"]["persona"] = "gandalf"
        resp = await admin_client.post(
            "/api/v1/story-courses", json={"content": course, "publish": True}
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["error"] == "cannot_publish_invalid_course"
        assert any(e["code"] == "tutor_persona_not_in_cast" for e in detail["errors"])

    async def test_refusal_lists_every_error(self, admin_client, course):
        course["minigames"] = []
        course["checks"] = {}
        resp = await admin_client.post(
            "/api/v1/story-courses", json={"content": course, "publish": True}
        )
        assert resp.status_code == 409
        codes = {e["code"] for e in resp.json()["detail"]["errors"]}
        assert {"missing_minigame", "missing_predicted_typical"} <= codes


class TestAuth:
    async def test_validate_requires_auth(self, anon_client, course):
        resp = await anon_client.post("/api/v1/story-courses/validate", json={"content": course})
        assert resp.status_code in (401, 403)

    async def test_catalog_requires_auth(self, anon_client):
        resp = await anon_client.get("/api/v1/story-courses")
        assert resp.status_code in (401, 403)

    async def test_detail_requires_auth(self, anon_client):
        resp = await anon_client.get("/api/v1/story-courses/igcse-maths-u1-w04")
        assert resp.status_code in (401, 403)
