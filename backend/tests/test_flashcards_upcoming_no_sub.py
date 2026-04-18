"""Regression tests for issues #1626 / #1619 — /api/v1/flashcards/upcoming
must return a 200 empty payload for users without an active subscription,
not a 403. The dashboard widget renders a neutral empty state when the
response is empty; it rendered a red error banner on the pre-fix 403.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from app.main import app


def _auth_headers() -> dict:
    from app.domain.services.jwt_auth_service import JWTAuthService

    svc = JWTAuthService()
    token = svc.create_access_token(
        user_id=str(uuid.uuid4()),
        email="learner@example.com",
        role="user",
    )
    return {"Authorization": f"Bearer {token}"}


async def test_upcoming_reviews_returns_200_empty_for_non_subscriber(
    client: AsyncClient,
) -> None:
    """No active subscription → 200 with zeros + empty sessions list."""
    fake_user = SimpleNamespace(
        id=uuid.uuid4(),
        email="learner@example.com",
        name="Learner",
    )

    # No active subscription.
    sub_svc = MagicMock()
    sub_svc.get_active_subscription = AsyncMock(return_value=None)

    with (
        patch(
            "app.api.v1.flashcards.get_current_user",
            new=AsyncMock(return_value=fake_user),
        ),
        patch(
            "app.api.v1.flashcards.SubscriptionService",
            return_value=sub_svc,
        ),
    ):
        from app.api.deps import get_db
        from app.api.deps_local_auth import get_current_user

        async def _noop_db():
            yield MagicMock()

        async def _fake_user_dep():
            return fake_user

        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _fake_user_dep
        try:
            response = await client.get(
                "/api/v1/flashcards/upcoming",
                headers=_auth_headers(),
            )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["today_due_count"] == 0
    assert body["has_due_cards"] is False
    assert body["upcoming_sessions"] == []


async def test_upcoming_reviews_never_403_for_non_subscriber(
    client: AsyncClient,
) -> None:
    """Defence-in-depth: the pre-fix 403 must not come back."""
    fake_user = SimpleNamespace(id=uuid.uuid4(), email="l@x", name="L")

    sub_svc = MagicMock()
    sub_svc.get_active_subscription = AsyncMock(return_value=None)

    with patch(
        "app.api.v1.flashcards.SubscriptionService",
        return_value=sub_svc,
    ):
        from app.api.deps import get_db
        from app.api.deps_local_auth import get_current_user

        async def _noop_db():
            yield MagicMock()

        async def _fake_user_dep():
            return fake_user

        app.dependency_overrides[get_db] = _noop_db
        app.dependency_overrides[get_current_user] = _fake_user_dep
        try:
            response = await client.get(
                "/api/v1/flashcards/upcoming",
                headers=_auth_headers(),
            )
        finally:
            app.dependency_overrides.clear()

    assert response.status_code != 403
