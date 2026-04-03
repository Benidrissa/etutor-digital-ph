"""Tests for course catalog and enrollment endpoints.

All data seeding is done via HTTP API calls (admin endpoints) to avoid
asyncpg 'another operation is in progress' errors that occur when test
fixtures share a SQLAlchemy session with the ASGI test client.
"""

import uuid

import pytest
from httpx import AsyncClient

from app.domain.services.jwt_auth_service import JWTAuthService

# ---------------------------------------------------------------------------
# Auth header helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_auth_headers():
    """JWT auth headers for a user with admin role."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="admin-user-uuid",
        email="admin@example.com",
        role="admin",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def learner_auth_headers():
    """JWT auth headers for a regular learner."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=str(uuid.uuid4()),
        email="learner@example.com",
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# API-based data seeding helpers
# ---------------------------------------------------------------------------


async def _create_course_via_api(
    client: AsyncClient,
    admin_headers: dict,
    slug: str,
    title_fr: str = "Cours test",
    title_en: str = "Test course",
    domain: str | None = None,
    estimated_hours: int = 20,
) -> dict:
    """Create a course via the admin API and return the response data."""
    payload = {
        "slug": slug,
        "title_fr": title_fr,
        "title_en": title_en,
        "estimated_hours": estimated_hours,
    }
    if domain:
        payload["domain"] = domain
    resp = await client.post(
        "/api/v1/admin/courses/",
        json=payload,
        headers=admin_headers,
    )
    assert resp.status_code == 201, f"Failed to create course: {resp.text}"
    return resp.json()


async def _publish_course_via_api(
    client: AsyncClient,
    admin_headers: dict,
    course_id: str,
) -> dict:
    """Publish a course via the admin API and return the response data."""
    resp = await client.post(
        f"/api/v1/admin/courses/{course_id}/publish",
        headers=admin_headers,
    )
    assert resp.status_code == 200, f"Failed to publish course: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Catalog tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_catalog_returns_only_published(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
    # Seed: one published, one draft
    pub = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"pub-{uuid.uuid4().hex[:8]}",
        title_fr="Cours publie",
        title_en="Published course",
    )
    pub = await _publish_course_via_api(authenticated_client, admin_auth_headers, pub["id"])

    draft = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        title_fr="Cours brouillon",
        title_en="Draft course",
    )

    resp = await authenticated_client.get("/api/v1/courses/")
    assert resp.status_code == 200
    data = resp.json()
    ids = [c["id"] for c in data["courses"]]
    assert pub["id"] in ids
    assert draft["id"] not in ids


@pytest.mark.asyncio
async def test_browse_catalog_no_auth_required(
    authenticated_client: AsyncClient,
):
    """Catalog endpoint should work without auth headers."""
    resp = await authenticated_client.get("/api/v1/courses/")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Enrollment tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enroll_creates_progress_records(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    auth_headers: dict,
):
    course = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"enroll-{uuid.uuid4().hex[:8]}",
    )
    course = await _publish_course_via_api(authenticated_client, admin_auth_headers, course["id"])

    resp = await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["course_id"] == course["id"]
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_enroll_twice_returns_conflict(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    auth_headers: dict,
):
    course = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"enroll2x-{uuid.uuid4().hex[:8]}",
    )
    course = await _publish_course_via_api(authenticated_client, admin_auth_headers, course["id"])

    await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=auth_headers,
    )
    resp = await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_enroll_draft_course_returns_404(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    auth_headers: dict,
):
    draft = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"draft-enroll-{uuid.uuid4().hex[:8]}",
    )

    resp = await authenticated_client.post(
        f"/api/v1/courses/{draft['id']}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Admin course management tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_create_course(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
    slug = f"nutrition-{uuid.uuid4().hex[:8]}"
    resp = await authenticated_client.post(
        "/api/v1/admin/courses/",
        json={
            "slug": slug,
            "title_fr": "Nutrition communautaire",
            "title_en": "Community nutrition",
            "domain": "Nutrition",
            "estimated_hours": 30,
        },
        headers=admin_auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == slug
    assert data["status"] == "draft"
    assert data["rag_collection_id"] == f"course_{slug}"


@pytest.mark.asyncio
async def test_admin_only_access_for_course_creation(
    authenticated_client: AsyncClient,
    auth_headers: dict,
):
    resp = await authenticated_client.post(
        "/api/v1/admin/courses/",
        json={
            "slug": "should-fail",
            "title_fr": "Test",
            "title_en": "Test",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_rag_collection_id_scoped_to_course(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
    slug = f"pharmacologie-{uuid.uuid4().hex[:8]}"
    resp = await authenticated_client.post(
        "/api/v1/admin/courses/",
        json={
            "slug": slug,
            "title_fr": "Pharmacologie tropicale",
            "title_en": "Tropical pharmacology",
            "domain": "Pharmacologie",
        },
        headers=admin_auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rag_collection_id"] == f"course_{slug}"


@pytest.mark.asyncio
async def test_publish_course(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
    draft = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"to-publish-{uuid.uuid4().hex[:8]}",
    )

    resp = await authenticated_client.post(
        f"/api/v1/admin/courses/{draft['id']}/publish",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert data["published_at"] is not None
