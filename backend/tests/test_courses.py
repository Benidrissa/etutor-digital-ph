"""Tests for multi-course system: catalog, enrollment, admin CRUD, RAG scoping."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select  # noqa: F401 — used in skipped tests

from app.domain.models.course import Course  # noqa: F401 — used in skipped tests
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


@pytest.fixture
def user_id_str():
    return str(uuid.uuid4())


@pytest.fixture
def user_with_id_headers(user_id_str):
    return _make_headers(role=UserRole.user.value, user_id=user_id_str)


@pytest.fixture
def admin_id_str():
    return str(uuid.uuid4())


@pytest.fixture
def admin_with_id_headers(admin_id_str):
    return _make_headers(role=UserRole.admin.value, user_id=admin_id_str)


# ---------------------------------------------------------------------------
# Admin-only access tests (no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_courses_requires_admin_role(user_headers):
    """GET /api/v1/admin/courses must return 403 for non-admin."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/v1/admin/courses", headers=user_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_course_requires_admin_role(user_headers):
    """POST /api/v1/admin/courses must return 403 for non-admin."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/admin/courses",
            json={"title_fr": "Test", "title_en": "Test"},
            headers=user_headers,
        )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Integration tests — skipped pending pytest-asyncio event loop fix
# See: https://github.com/Benidrissa/etutor-digital-ph/issues/554
# ---------------------------------------------------------------------------

_SKIP_REASON = (
    "pytest-asyncio 1.3.0 event loop conflict with async DB fixtures — "
    "tracked in issue #554"
)


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_catalog_accessible_without_auth(authenticated_client):
    """GET /api/v1/courses must return 200 without auth (no auth header sent)."""
    response = await authenticated_client.get("/api/v1/courses")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# DB integration tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_create_course_saves_to_db(authenticated_client, db_session, admin_with_id_headers):
    """Admin can create a course and it is saved to the database."""
    response = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={
            "title_fr": "Nutrition Communautaire",
            "title_en": "Community Nutrition",
            "domain": "Nutrition",
            "estimated_hours": 40,
        },
        headers=admin_with_id_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title_en"] == "Community Nutrition"
    assert data["status"] == "draft"
    assert data["slug"].startswith("community-nutrition")

    result = await db_session.execute(select(Course).where(Course.id == uuid.UUID(data["id"])))
    course = result.scalar_one_or_none()
    assert course is not None
    assert course.title_fr == "Nutrition Communautaire"


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_publish_course(authenticated_client, db_session, admin_with_id_headers):
    """Admin can publish a draft course; it becomes visible in catalog."""
    create_resp = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={"title_fr": "Pharmacologie", "title_en": "Pharmacology"},
        headers=admin_with_id_headers,
    )
    assert create_resp.status_code == 201
    course_id = create_resp.json()["id"]

    pub_resp = await authenticated_client.post(
        f"/api/v1/admin/courses/{course_id}/publish",
        headers=admin_with_id_headers,
    )
    assert pub_resp.status_code == 200
    assert pub_resp.json()["status"] == "published"
    assert pub_resp.json()["published_at"] is not None


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_enrollment_creates_progress_records(
    authenticated_client, db_session, admin_with_id_headers, user_with_id_headers, user_id_str
):
    """Enrolling in a course initializes UserModuleProgress for all course modules."""
    from app.domain.models.module import Module
    from app.domain.models.progress import UserModuleProgress

    create_resp = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={"title_fr": "Épidémiologie", "title_en": "Epidemiology"},
        headers=admin_with_id_headers,
    )
    course_id = uuid.UUID(create_resp.json()["id"])

    module = Module(
        id=uuid.uuid4(),
        module_number=9001,
        level=1,
        title_fr="Module test",
        title_en="Test module",
        course_id=course_id,
    )
    db_session.add(module)
    await db_session.flush()

    pub_resp = await authenticated_client.post(
        f"/api/v1/admin/courses/{course_id}/publish",
        headers=admin_with_id_headers,
    )
    assert pub_resp.status_code == 200

    enroll_resp = await authenticated_client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers=user_with_id_headers,
    )
    assert enroll_resp.status_code == 200
    enroll_data = enroll_resp.json()
    assert enroll_data["status"] == "active"

    progress_result = await db_session.execute(
        select(UserModuleProgress).where(
            UserModuleProgress.user_id == uuid.UUID(user_id_str),
            UserModuleProgress.module_id == module.id,
        )
    )
    progress = progress_result.scalar_one_or_none()
    assert progress is not None
    assert progress.status == "locked"


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_duplicate_enrollment_returns_existing(
    authenticated_client, admin_with_id_headers, user_with_id_headers, user_id_str
):
    """Enrolling twice in the same course returns the existing enrollment."""
    create_resp = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={"title_fr": "Biostatistiques", "title_en": "Biostatistics"},
        headers=admin_with_id_headers,
    )
    course_id = create_resp.json()["id"]

    await authenticated_client.post(
        f"/api/v1/admin/courses/{course_id}/publish",
        headers=admin_with_id_headers,
    )

    resp1 = await authenticated_client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers=user_with_id_headers,
    )
    resp2 = await authenticated_client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers=user_with_id_headers,
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["enrolled_at"] == resp2.json()["enrolled_at"]


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_enroll_in_unpublished_course_returns_404(
    authenticated_client, admin_with_id_headers, user_with_id_headers
):
    """Enrolling in a draft course must return 404."""
    create_resp = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={"title_fr": "Brouillon", "title_en": "Draft course"},
        headers=admin_with_id_headers,
    )
    course_id = create_resp.json()["id"]

    enroll_resp = await authenticated_client.post(
        f"/api/v1/courses/{course_id}/enroll",
        headers=user_with_id_headers,
    )
    assert enroll_resp.status_code == 404


@pytest.mark.skip(reason=_SKIP_REASON)
@pytest.mark.asyncio
async def test_rag_collection_id_scoping(authenticated_client, admin_with_id_headers):
    """Course rag_collection_id is stored and returned in the response."""
    rag_id = "course-nutrition-v1"
    create_resp = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={
            "title_fr": "RAG Test",
            "title_en": "RAG Test",
            "rag_collection_id": rag_id,
        },
        headers=admin_with_id_headers,
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["rag_collection_id"] == rag_id
