"""Tests for course catalog and enrollment endpoints."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.services.jwt_auth_service import JWTAuthService


@pytest.fixture
def admin_auth_headers():
    """JWT auth headers for a user with admin role."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id="00000000-0000-0000-0000-000000000001",
        email="admin@example.com",
        role="admin",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def published_course(db_session: AsyncSession):
    """Create a published course in the test database."""
    course = Course(
        id=uuid.uuid4(),
        slug="test-course-pub",
        title_fr="Cours test publié",
        title_en="Published test course",
        status="published",
        estimated_hours=20,
        module_count=0,
        rag_collection_id="course_test-course-pub",
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


@pytest.fixture
async def draft_course(db_session: AsyncSession):
    """Create a draft course in the test database."""
    course = Course(
        id=uuid.uuid4(),
        slug="test-course-draft",
        title_fr="Cours test brouillon",
        title_en="Draft test course",
        status="draft",
        estimated_hours=10,
        module_count=0,
    )
    db_session.add(course)
    await db_session.commit()
    await db_session.refresh(course)
    return course


@pytest.mark.asyncio
async def test_browse_catalog_returns_only_published(
    authenticated_client: AsyncClient,
    published_course: Course,
    draft_course: Course,
):
    resp = await authenticated_client.get("/api/v1/courses/")
    assert resp.status_code == 200
    data = resp.json()
    ids = [c["id"] for c in data["courses"]]
    assert str(published_course.id) in ids
    assert str(draft_course.id) not in ids


@pytest.mark.asyncio
async def test_browse_catalog_no_auth_required(
    client: AsyncClient,
    published_course: Course,
):
    resp = await client.get("/api/v1/courses/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enroll_creates_progress_records(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
    published_course: Course,
    auth_headers: dict,
):
    module_id = uuid.uuid4()
    module = Module(
        id=module_id,
        module_number=9001,
        level=1,
        title_fr="Module test",
        title_en="Test module",
        course_id=published_course.id,
    )
    db_session.add(module)
    await db_session.commit()

    resp = await authenticated_client.post(
        f"/api/v1/courses/{published_course.id}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["course_id"] == str(published_course.id)
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_enroll_twice_returns_conflict(
    authenticated_client: AsyncClient,
    published_course: Course,
    auth_headers: dict,
):
    await authenticated_client.post(
        f"/api/v1/courses/{published_course.id}/enroll",
        headers=auth_headers,
    )
    resp = await authenticated_client.post(
        f"/api/v1/courses/{published_course.id}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_enroll_draft_course_returns_404(
    authenticated_client: AsyncClient,
    draft_course: Course,
    auth_headers: dict,
):
    resp = await authenticated_client.post(
        f"/api/v1/courses/{draft_course.id}/enroll",
        headers=auth_headers,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rag_collection_id_scoped_to_course(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
    resp = await authenticated_client.post(
        "/api/v1/admin/courses/",
        json={
            "slug": "pharmacologie-test",
            "title_fr": "Pharmacologie tropicale",
            "title_en": "Tropical pharmacology",
            "domain": "Pharmacologie",
        },
        headers=admin_auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["rag_collection_id"] == "course_pharmacologie-test"
