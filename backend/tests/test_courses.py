"""Tests for multi-course system: catalog, enrollment, admin CRUD, RAG scoping.

All tests use inline AsyncClient (no authenticated_client fixture) to avoid
pytest-asyncio event loop conflicts. Assertions are on HTTP responses only.
"""

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


def _admin_headers(user_id: str | None = None) -> dict:
    return _make_headers(role=UserRole.admin.value, user_id=user_id or str(uuid.uuid4()))


def _user_headers(user_id: str | None = None) -> dict:
    return _make_headers(role=UserRole.user.value, user_id=user_id or str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Admin-only access tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_courses_requires_admin_role():
    """GET /api/v1/admin/courses must return 403 for non-admin."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/courses", headers=_user_headers())
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_course_requires_admin_role():
    """POST /api/v1/admin/courses must return 403 for non-admin."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Test", "title_en": "Test"},
            headers=_user_headers(),
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Catalog access tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_catalog_accessible_without_auth():
    """GET /api/v1/courses must return 200 without auth."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/courses")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Course CRUD tests (via API only — no direct DB assertions)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_course_returns_draft():
    """Admin can create a course; response has correct fields."""
    headers = _admin_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/admin/courses",
            json={
                "title_fr": "Nutrition Communautaire",
                "title_en": "Community Nutrition",
                "domain": "Nutrition",
                "estimated_hours": 40,
            },
            headers=headers,
        )
    assert response.status_code == 201
    data = response.json()
    assert data["title_en"] == "Community Nutrition"
    assert data["title_fr"] == "Nutrition Communautaire"
    assert data["status"] == "draft"
    assert data["slug"].startswith("community-nutrition")
    assert "id" in data


@pytest.mark.asyncio
async def test_publish_course():
    """Admin can publish a draft course."""
    headers = _admin_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Pharmacologie", "title_en": "Pharmacology"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        course_id = create_resp.json()["id"]

        pub_resp = await ac.post(
            f"/api/v1/admin/courses/{course_id}/publish",
            headers=headers,
        )
    assert pub_resp.status_code == 200
    assert pub_resp.json()["status"] == "published"
    assert pub_resp.json()["published_at"] is not None


@pytest.mark.asyncio
async def test_enroll_in_published_course():
    """User can enroll in a published course."""
    admin_h = _admin_headers()
    user_h = _user_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Épidémiologie", "title_en": "Epidemiology"},
            headers=admin_h,
        )
        assert create_resp.status_code == 201
        course_id = create_resp.json()["id"]

        await ac.post(
            f"/api/v1/admin/courses/{course_id}/publish",
            headers=admin_h,
        )

        enroll_resp = await ac.post(
            f"/api/v1/courses/{course_id}/enroll",
            headers=user_h,
        )
    assert enroll_resp.status_code == 200
    assert enroll_resp.json()["status"] == "active"
    assert "enrolled_at" in enroll_resp.json()


@pytest.mark.asyncio
async def test_duplicate_enrollment_returns_existing():
    """Enrolling twice returns the existing enrollment."""
    admin_h = _admin_headers()
    user_h = _user_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Biostatistiques", "title_en": "Biostatistics"},
            headers=admin_h,
        )
        course_id = create_resp.json()["id"]

        await ac.post(
            f"/api/v1/admin/courses/{course_id}/publish",
            headers=admin_h,
        )

        resp1 = await ac.post(
            f"/api/v1/courses/{course_id}/enroll",
            headers=user_h,
        )
        resp2 = await ac.post(
            f"/api/v1/courses/{course_id}/enroll",
            headers=user_h,
        )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["enrolled_at"] == resp2.json()["enrolled_at"]


@pytest.mark.asyncio
async def test_enroll_in_unpublished_course_returns_404():
    """Enrolling in a draft course must return 404."""
    admin_h = _admin_headers()
    user_h = _user_headers()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Brouillon", "title_en": "Draft course"},
            headers=admin_h,
        )
        course_id = create_resp.json()["id"]

        enroll_resp = await ac.post(
            f"/api/v1/courses/{course_id}/enroll",
            headers=user_h,
        )
    assert enroll_resp.status_code == 404


@pytest.mark.asyncio
async def test_rag_collection_id_stored():
    """Course rag_collection_id is stored and returned in the response."""
    headers = _admin_headers()
    rag_id = "course-nutrition-v1"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post(
            "/api/v1/admin/courses",
            json={
                "title_fr": "RAG Test",
                "title_en": "RAG Test",
                "rag_collection_id": rag_id,
            },
            headers=headers,
        )
    assert create_resp.status_code == 201
    assert create_resp.json()["rag_collection_id"] == rag_id
