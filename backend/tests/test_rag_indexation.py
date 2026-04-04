"""Tests for admin RAG indexation API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.domain.models.user import UserRole
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app


def _make_headers(role: str = "user", user_id: str | None = None) -> dict:
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=user_id or str(uuid.uuid4()),
        email=f"{role}@example.com",
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return _make_headers(role=UserRole.admin.value, user_id=str(uuid.uuid4()))


@pytest.fixture
def user_headers():
    return _make_headers(role=UserRole.user.value)


@pytest.mark.asyncio
async def test_trigger_indexation_requires_admin(user_headers):
    """POST /api/v1/admin/courses/{id}/index-resources returns 403 for non-admin."""
    course_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/admin/courses/{course_id}/index-resources",
            headers=user_headers,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_get_index_status_requires_admin(user_headers):
    """GET /api/v1/admin/courses/{id}/index-status returns 403 for non-admin."""
    course_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get(
            f"/api/v1/admin/courses/{course_id}/index-status",
            headers=user_headers,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_trigger_indexation_404_on_missing_course(admin_headers):
    """POST /index-resources returns 404 when course does not exist."""
    course_id = str(uuid.uuid4())
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    from app.api.deps import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/admin/courses/{course_id}/index-resources",
                headers=admin_headers,
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_index_status_404_on_missing_course(admin_headers):
    """GET /index-status returns 404 when course does not exist."""
    course_id = str(uuid.uuid4())
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    from app.api.deps import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                f"/api/v1/admin/courses/{course_id}/index-status",
                headers=admin_headers,
            )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_publish_blocked_when_not_indexed(admin_headers):
    """POST /publish returns 400 when RAG indexation is not complete."""
    from app.domain.models.course import Course

    course_id = uuid.uuid4()
    mock_course = Course(
        id=course_id,
        slug="test-course",
        title_fr="Test FR",
        title_en="Test EN",
        status="draft",
        languages="fr,en",
        estimated_hours=20,
        module_count=0,
        rag_collection_id="test-collection",
    )

    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar_one_or_none.return_value = mock_course
        elif call_count == 2:
            mock_result.mappings.return_value.one_or_none.return_value = None
        return mock_result

    mock_db.execute = mock_execute

    from app.api.deps import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/admin/courses/{course_id}/publish",
                headers=admin_headers,
            )
        assert response.status_code == 400
        data = response.json()
        assert "RAG indexation" in data["detail"]
        assert "not_started" in data["detail"]
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_index_status_returns_not_started_when_no_job(admin_headers):
    """GET /index-status returns state=not_started when no jobs exist for course."""
    from app.domain.models.course import Course

    course_id = uuid.uuid4()
    mock_course = Course(
        id=course_id,
        slug="test-course",
        title_fr="Test FR",
        title_en="Test EN",
        status="draft",
        languages="fr,en",
        estimated_hours=20,
        module_count=0,
        rag_collection_id="test-collection",
    )

    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar_one_or_none.return_value = mock_course
        else:
            mock_result.mappings.return_value.one_or_none.return_value = None
        return mock_result

    mock_db.execute = mock_execute

    from app.api.deps import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get(
                f"/api/v1/admin/courses/{course_id}/index-status",
                headers=admin_headers,
            )
        assert response.status_code == 200
        data = response.json()
        assert data["state"] == "not_started"
        assert data["job_id"] is None
        assert data["progress_pct"] == 0.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_indexation_409_when_already_in_progress(admin_headers):
    """POST /index-resources returns 409 when indexation is already running."""
    from app.domain.models.course import Course

    course_id = uuid.uuid4()
    job_id = uuid.uuid4()
    mock_course = Course(
        id=course_id,
        slug="test-course",
        title_fr="Test FR",
        title_en="Test EN",
        status="draft",
        languages="fr,en",
        estimated_hours=20,
        module_count=0,
        rag_collection_id="test-collection",
    )

    existing_job = {
        "id": job_id,
        "celery_task_id": "task-123",
        "state": "embedding",
        "chunk_count": None,
        "progress_pct": 50.0,
        "error_message": None,
        "created_at": None,
        "updated_at": None,
        "completed_at": None,
    }

    mock_db = AsyncMock()
    call_count = 0

    async def mock_execute(query, params=None):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        if call_count == 1:
            mock_result.scalar_one_or_none.return_value = mock_course
        else:
            mock_result.mappings.return_value.one_or_none.return_value = existing_job
        return mock_result

    mock_db.execute = mock_execute

    from app.api.deps import get_db

    async def override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.post(
                f"/api/v1/admin/courses/{course_id}/index-resources",
                headers=admin_headers,
            )
        assert response.status_code == 409
        assert "already in progress" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
