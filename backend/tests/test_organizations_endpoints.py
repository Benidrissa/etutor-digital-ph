"""Tests for the GET /api/v1/organizations endpoint added in #2129.

Asserts the canonical RESTful path returns the same payload as ``/me`` and
covers the unauthenticated case.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.main import app


def _membership(role: str = "owner") -> dict:
    org = MagicMock()
    org.id = uuid.uuid4()
    org.name = "Acme"
    org.slug = "acme"
    org.description = None
    org.logo_url = None
    org.contact_email = None
    org.is_active = True
    org.created_at = datetime(2026, 1, 1, 12, 0, 0)
    return {
        "organization": org,
        "role": role,
        "joined_at": datetime(2026, 2, 1, 12, 0, 0),
    }


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


@pytest.fixture
def override_db():
    mock_db = AsyncMock()
    app.dependency_overrides[get_db_session] = lambda: mock_db
    yield mock_db
    app.dependency_overrides.pop(get_db_session, None)


async def test_list_organizations_unauthenticated_is_rejected() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/organizations")
    assert resp.status_code in (401, 403)
    assert resp.status_code != 405


async def test_list_organizations_returns_user_memberships(
    override_user, override_db, monkeypatch
) -> None:
    rows = [_membership("owner"), _membership("viewer")]
    monkeypatch.setattr(
        "app.api.v1.organizations._svc.list_user_organizations",
        AsyncMock(return_value=rows),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/v1/organizations")

    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert {p["role"] for p in payload} == {"owner", "viewer"}
    first = payload[0]
    assert first["organization"]["slug"] == "acme"
    assert first["organization"]["name"] == "Acme"
    assert first["organization"]["is_active"] is True
    assert first["joined_at"].startswith("2026-02-01")


async def test_list_organizations_matches_me_endpoint(
    override_user, override_db, monkeypatch
) -> None:
    rows = [_membership("admin")]
    monkeypatch.setattr(
        "app.api.v1.organizations._svc.list_user_organizations",
        AsyncMock(return_value=rows),
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        root = await ac.get("/api/v1/organizations")
        me = await ac.get("/api/v1/organizations/me")

    assert root.status_code == 200
    assert me.status_code == 200
    assert root.json() == me.json()
