"""Tests for admin RAG management endpoints."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, get_db_session
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app


def _make_admin_headers(role: str = "admin") -> dict[str, str]:
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="admin-uuid",
        email="admin@example.com",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_user_headers() -> dict[str, str]:
    return _make_admin_headers(role="user")


@pytest.fixture
async def admin_client():
    """Test client with admin JWT (no DB override needed for unit tests)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def user_client():
    """Test client with regular user JWT."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestRequireAdmin:
    async def test_user_role_rejected(self, admin_client: AsyncClient):
        """Non-admin users must receive 403."""
        headers = _make_user_headers()
        with patch(
            "app.api.v1.admin.rag.get_db",
            return_value=AsyncMock(),
        ):
            resp = await admin_client.get("/api/v1/admin/rag/status", headers=headers)
        assert resp.status_code == 403

    async def test_unauthenticated_rejected(self, admin_client: AsyncClient):
        """Unauthenticated requests must receive 401 or 403."""
        resp = await admin_client.get("/api/v1/admin/rag/status")
        assert resp.status_code in (401, 403)


class TestRagStatus:
    async def test_status_returns_stats(self, admin_client: AsyncClient):
        """GET /admin/rag/status returns index stats."""
        headers = _make_admin_headers()

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_db_session] = _override_db

        try:
            resp = await admin_client.get("/api/v1/admin/rag/status", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "total_chunks" in data
            assert "sources" in data
            assert isinstance(data["sources"], list)
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_db_session, None)


class TestRagReindex:
    async def test_reindex_triggers_celery_task(self, admin_client: AsyncClient):
        """POST /admin/rag/reindex dispatches a Celery task."""
        headers = _make_admin_headers()

        mock_task = MagicMock()
        mock_task.id = "test-task-id-123"

        with (
            patch("app.api.v1.admin.rag.reindex_source") as mock_reindex,
            patch("app.api.v1.admin.rag.redis_client") as mock_redis,
        ):
            mock_reindex.delay.return_value = mock_task
            mock_redis.setex = AsyncMock()

            resp = await admin_client.post(
                "/api/v1/admin/rag/reindex",
                json={},
                headers=headers,
            )

        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "pending"
        assert "job_id" in data
        mock_reindex.delay.assert_called_once_with(source_id=None)

    async def test_selective_reindex(self, admin_client: AsyncClient):
        """POST /admin/rag/reindex with source_id triggers selective re-index."""
        headers = _make_admin_headers()
        mock_task = MagicMock()
        mock_task.id = "task-selective-456"

        with (
            patch("app.api.v1.admin.rag.reindex_source") as mock_reindex,
            patch("app.api.v1.admin.rag.redis_client") as mock_redis,
        ):
            mock_reindex.delay.return_value = mock_task
            mock_redis.setex = AsyncMock()

            resp = await admin_client.post(
                "/api/v1/admin/rag/reindex",
                json={"source_id": "donaldson"},
                headers=headers,
            )

        assert resp.status_code == 202
        mock_reindex.delay.assert_called_once_with(source_id="donaldson")

    async def test_reindex_rejected_for_non_admin(self, admin_client: AsyncClient):
        headers = _make_user_headers()
        resp = await admin_client.post(
            "/api/v1/admin/rag/reindex",
            json={},
            headers=headers,
        )
        assert resp.status_code == 403


class TestRagDeleteSource:
    async def test_delete_source_removes_chunks(self, admin_client: AsyncClient):
        """DELETE /admin/rag/source/{id} removes chunks."""
        headers = _make_admin_headers()

        mock_db = AsyncMock()

        count_result = MagicMock()
        count_result.scalar.return_value = 42

        mock_db.execute = AsyncMock(return_value=count_result)
        mock_db.commit = AsyncMock()

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_db_session] = _override_db

        try:
            resp = await admin_client.delete(
                "/api/v1/admin/rag/source/donaldson",
                headers=headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["chunks_removed"] == 42
            assert data["source_id"] == "donaldson"
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_db_session, None)

    async def test_delete_source_not_found(self, admin_client: AsyncClient):
        """DELETE returns 404 when source has no chunks."""
        headers = _make_admin_headers()

        mock_db = AsyncMock()
        count_result = MagicMock()
        count_result.scalar.return_value = 0
        mock_db.execute = AsyncMock(return_value=count_result)

        async def _override_db():
            yield mock_db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_db_session] = _override_db

        try:
            resp = await admin_client.delete(
                "/api/v1/admin/rag/source/nonexistent",
                headers=headers,
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_db_session, None)


class TestRagJobs:
    async def test_jobs_returns_list(self, admin_client: AsyncClient):
        """GET /admin/rag/jobs returns a list of jobs."""
        headers = _make_admin_headers()

        import json

        job_data = json.dumps(
            {
                "job_id": "abc-123",
                "status": "completed",
                "updated_at": 1700000000,
                "source": "donaldson",
                "chunks_indexed": 150,
            }
        )

        with patch("app.api.v1.admin.rag.redis_client") as mock_redis:
            mock_redis.scan_iter = MagicMock(return_value=_async_gen(["rag:job:abc-123"]))
            mock_redis.get = AsyncMock(return_value=job_data)

            resp = await admin_client.get("/api/v1/admin/rag/jobs", headers=headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert isinstance(data["jobs"], list)

    async def test_jobs_rejected_for_non_admin(self, admin_client: AsyncClient):
        headers = _make_user_headers()
        resp = await admin_client.get("/api/v1/admin/rag/jobs", headers=headers)
        assert resp.status_code == 403


async def _async_gen(items):
    for item in items:
        yield item
