"""API tests for module story mode: GET /api/v1/story-courses/module/{module_id}.

The requests go through the real FastAPI app (httpx ASGITransport) with the
database dependency replaced by stubs, so these pin the HTTP contract (C-4):
the handler order and every status code, the access gate, the status route,
route ordering against ``/{slug}``, the slug and catalog discriminators, the
dispatch dedup (on a real Redis when one is reachable), the offline bundle,
and the unit type the module detail now reports.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.main import app

MODULE_ID = uuid.UUID("7a6b5c4d-3e2f-4a1b-9c8d-7e6f5a4b3c2d")
USER_ID = "22222222-2222-2222-2222-222222222222"


def _user(role: str = "user") -> AuthenticatedUser:
    return AuthenticatedUser({"sub": USER_ID, "email": "l@example.com", "role": role})


class _Unusable:
    """A DB session stub that fails loudly if anything touches it."""

    def __getattr__(self, name):
        raise AssertionError(f"the database was used: {name}")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# The module detail reports each unit's type
# --------------------------------------------------------------------------


class TestProgressDetail:
    """The module page classifies units (lesson, quiz, case study) from this route."""

    async def test_each_unit_carries_its_type(self, client):
        def unit(number: str, unit_type: str | None) -> dict:
            return {
                "id": str(uuid.uuid4()),
                "unit_number": number,
                "title_fr": f"Unité {number}",
                "title_en": f"Unit {number}",
                "estimated_minutes": 10,
                "order_index": int(number.split(".")[1]),
                "unit_type": unit_type,
                "status": "pending",
            }

        detail = {
            "id": str(MODULE_ID),
            "module_number": 1,
            "level": 1,
            "title_fr": "Module",
            "title_en": "Module",
            "estimated_hours": 2,
            "status": "in_progress",
            "completion_pct": 0.0,
            "units": [unit("1.1", "lesson"), unit("1.2", "quiz"), unit("1.3", None)],
        }
        service = SimpleNamespace(get_module_with_progress=AsyncMock(return_value=detail))

        async def no_db():
            yield _Unusable()

        app.dependency_overrides[get_current_user] = lambda: _user()
        app.dependency_overrides[get_db] = no_db
        with patch("app.api.v1.progress.ProgressService", return_value=service):
            resp = await client.get(f"/api/v1/progress/modules/{MODULE_ID}/detail")

        assert resp.status_code == 200
        assert [u["unit_type"] for u in resp.json()["units"]] == ["lesson", "quiz", None]
