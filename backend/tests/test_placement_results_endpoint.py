"""Tests for GET /api/v1/placement-test/results endpoint."""

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app


def _make_mock_user(user_id: str = "test-user-uuid") -> MagicMock:
    user = MagicMock()
    user.id = uuid.UUID(user_id) if len(user_id) == 36 else uuid.uuid4()
    user.preferred_language = "fr"
    return user


def _make_mock_attempt(
    user_id: uuid.UUID,
    raw_score: float = 70.0,
    assigned_level: int = 2,
    can_retake_after: datetime | None = None,
) -> MagicMock:
    attempt = MagicMock()
    attempt.id = uuid.uuid4()
    attempt.user_id = user_id
    attempt.raw_score = raw_score
    attempt.assigned_level = assigned_level
    attempt.attempted_at = datetime(2025, 1, 15, 10, 0, 0)
    attempt.domain_scores = {
        "level_1_foundations": 80.0,
        "level_2_epidemiology": 60.0,
        "level_3_advanced": 40.0,
        "level_4_expert": 20.0,
    }
    attempt.can_retake_after = can_retake_after
    return attempt


class TestGetPlacementResultsHistory:
    async def test_unauthenticated_returns_401(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/placement-test/results")
        assert response.status_code == 401

    async def test_empty_results_returns_empty_array(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        mock_user = _make_mock_user()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        with (
            patch(
                "app.api.deps_local_auth.get_current_user",
                return_value=mock_user,
            ),
            patch(
                "app.api.v1.placement.get_current_user",
                return_value=mock_user,
            ),
        ):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)

            from app.api.deps import get_db

            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/placement-test/results", headers=auth_headers)

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["attempts"] == []
        assert data["total_attempts"] == 0
        assert data["can_retake_now"] is True
        assert data["next_retake_at"] is None

    async def test_returns_attempts_with_correct_fields(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        mock_user = _make_mock_user()
        attempt = _make_mock_attempt(mock_user.id)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [attempt]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        with (
            patch("app.api.v1.placement.get_current_user", return_value=mock_user),
        ):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)

            from app.api.deps import get_db

            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/placement-test/results", headers=auth_headers)

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["total_attempts"] == 1
        assert len(data["attempts"]) == 1

        first = data["attempts"][0]
        assert "id" in first
        assert "attempt_number" in first
        assert "attempted_at" in first
        assert "score_percentage" in first
        assert "assigned_level" in first
        assert "domain_scores" in first
        assert first["score_percentage"] == 70.0
        assert first["assigned_level"] == 2

    async def test_can_retake_now_when_retake_date_passed(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        mock_user = _make_mock_user()
        past_date = datetime.utcnow() - timedelta(days=1)
        attempt = _make_mock_attempt(mock_user.id, can_retake_after=past_date)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [attempt]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        with patch("app.api.v1.placement.get_current_user", return_value=mock_user):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)

            from app.api.deps import get_db

            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/placement-test/results", headers=auth_headers)

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["can_retake_now"] is True
        assert data["next_retake_at"] is None

    async def test_cannot_retake_when_retake_date_in_future(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        mock_user = _make_mock_user()
        future_date = datetime.utcnow() + timedelta(days=90)
        attempt = _make_mock_attempt(mock_user.id, can_retake_after=future_date)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [attempt]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        with patch("app.api.v1.placement.get_current_user", return_value=mock_user):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)

            from app.api.deps import get_db

            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/placement-test/results", headers=auth_headers)

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["can_retake_now"] is False
        assert data["next_retake_at"] is not None

    async def test_domain_scores_included_in_response(
        self, client: AsyncClient, auth_headers: dict
    ) -> None:
        mock_user = _make_mock_user()
        attempt = _make_mock_attempt(mock_user.id)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [attempt]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        with patch("app.api.v1.placement.get_current_user", return_value=mock_user):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_result)

            from app.api.deps import get_db

            app.dependency_overrides[get_db] = lambda: mock_db

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                response = await ac.get("/api/v1/placement-test/results", headers=auth_headers)

            app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        domain_scores = data["attempts"][0]["domain_scores"]
        assert "level_1_foundations" in domain_scores
        assert domain_scores["level_1_foundations"] == 80.0
