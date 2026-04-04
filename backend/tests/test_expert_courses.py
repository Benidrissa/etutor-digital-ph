"""Tests for expert course management endpoints."""

import uuid

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
def expert_headers():
    return _make_headers(role=UserRole.expert.value, user_id=str(uuid.uuid4()))


@pytest.fixture
def user_headers():
    return _make_headers(role=UserRole.user.value)


@pytest.fixture
def admin_headers():
    return _make_headers(role=UserRole.admin.value)


@pytest.mark.asyncio
async def test_list_expert_courses_requires_expert_role(user_headers):
    """GET /api/v1/expert/courses must return 403 for non-expert users."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/expert/courses", headers=user_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_expert_course_requires_expert_role(user_headers):
    """POST /api/v1/expert/courses must return 403 for non-expert users."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/expert/courses",
            json={"title_fr": "Test", "title_en": "Test"},
            headers=user_headers,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_expert_courses_requires_auth():
    """GET /api/v1/expert/courses must return 403 without auth."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/expert/courses")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_access_expert_routes(admin_headers):
    """Admin role must return 403 on expert-only endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/expert/courses", headers=admin_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_set_price_requires_expert_role(user_headers):
    """POST /api/v1/expert/courses/{id}/set-price must return 403 for non-expert."""
    course_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/expert/courses/{course_id}/set-price",
            json={"credit_price": 10},
            headers=user_headers,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_publish_requires_expert_role(user_headers):
    """POST /api/v1/expert/courses/{id}/publish must return 403 for non-expert."""
    course_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/expert/courses/{course_id}/publish",
            headers=user_headers,
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_index_resources_requires_expert_role(user_headers):
    """POST /api/v1/expert/courses/{id}/index-resources must return 403 for non-expert."""
    course_id = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            f"/api/v1/expert/courses/{course_id}/index-resources",
            headers=user_headers,
        )
    assert response.status_code == 403
