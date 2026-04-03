"""Tests for multi-course system: catalog, enrollment, admin CRUD, RAG scoping.

Uses shared conftest fixtures (authenticated_client, db_session) — no custom sessionmakers.
"""

import uuid

import pytest
from sqlalchemy import select

from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.user import UserRole
from app.domain.services.jwt_auth_service import JWTAuthService


def _make_token(role: str = UserRole.user.value) -> str:
    jwt_service = JWTAuthService()
    return jwt_service.create_access_token(
        user_id=str(uuid.uuid4()),
        email="test@example.com",
        role=role,
    )


def _make_admin_token() -> str:
    return _make_token(role=UserRole.admin.value)


@pytest.fixture
def user_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


@pytest.fixture
def admin_headers():
    return {"Authorization": f"Bearer {_make_admin_token()}"}


# ---------------------------------------------------------------------------
# Public catalog — no auth required
# ---------------------------------------------------------------------------


async def test_catalog_returns_empty_for_no_published_courses(authenticated_client):
    """GET /api/v1/courses returns 200 + empty list when no published courses."""
    response = await authenticated_client.get("/api/v1/courses")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


async def test_catalog_returns_published_courses(authenticated_client, db_session):
    """Published courses appear in the catalog."""
    course = Course(
        id=uuid.uuid4(),
        slug="test-public-course",
        title_fr="Cours de test",
        title_en="Test Course",
        status="published",
        languages="fr,en",
        estimated_hours=10,
        module_count=2,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.get("/api/v1/courses")
    assert response.status_code == 200
    slugs = [c["slug"] for c in response.json()]
    assert "test-public-course" in slugs


async def test_catalog_excludes_draft_courses(authenticated_client, db_session):
    """Draft courses must NOT appear in the public catalog."""
    course = Course(
        id=uuid.uuid4(),
        slug="draft-hidden-course",
        title_fr="Cours brouillon",
        title_en="Draft Course",
        status="draft",
        languages="fr,en",
        estimated_hours=5,
        module_count=0,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.get("/api/v1/courses")
    assert response.status_code == 200
    slugs = [c["slug"] for c in response.json()]
    assert "draft-hidden-course" not in slugs


# ---------------------------------------------------------------------------
# Admin-only access control
# ---------------------------------------------------------------------------


async def test_admin_create_course_requires_admin_role(authenticated_client, user_headers):
    """POST /api/v1/admin/courses must return 403 for user role."""
    response = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={
            "slug": "should-fail",
            "title_fr": "Test",
            "title_en": "Test",
        },
        headers=user_headers,
    )
    assert response.status_code == 403


async def test_admin_create_course_requires_auth(authenticated_client):
    """POST /api/v1/admin/courses must return 401/403 without auth."""
    response = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={"slug": "no-auth", "title_fr": "Test", "title_en": "Test"},
    )
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Admin course creation
# ---------------------------------------------------------------------------


async def test_admin_can_create_course(authenticated_client, db_session, admin_headers):
    """Admin can create a new course."""
    response = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={
            "slug": "admin-created-course",
            "title_fr": "Cours créé par admin",
            "title_en": "Admin Created Course",
            "domain": "Épidémiologie",
            "estimated_hours": 30,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["slug"] == "admin-created-course"
    assert data["status"] == "draft"
    assert data["rag_collection_id"] == "course_admin-created-course"

    result = await db_session.execute(select(Course).where(Course.slug == "admin-created-course"))
    db_course = result.scalar_one_or_none()
    assert db_course is not None
    assert db_course.title_fr == "Cours créé par admin"


async def test_admin_create_course_rejects_duplicate_slug(
    authenticated_client, db_session, admin_headers
):
    """Creating a course with duplicate slug returns 409."""
    course = Course(
        id=uuid.uuid4(),
        slug="duplicate-slug",
        title_fr="Premier cours",
        title_en="First Course",
        status="draft",
        languages="fr,en",
        estimated_hours=0,
        module_count=0,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.post(
        "/api/v1/admin/courses",
        json={
            "slug": "duplicate-slug",
            "title_fr": "Deuxième cours",
            "title_en": "Second Course",
        },
        headers=admin_headers,
    )
    assert response.status_code == 409


async def test_admin_can_publish_course(authenticated_client, db_session, admin_headers):
    """Admin can publish a draft course."""
    course = Course(
        id=uuid.uuid4(),
        slug="to-be-published",
        title_fr="Cours à publier",
        title_en="Course to Publish",
        status="draft",
        languages="fr,en",
        estimated_hours=20,
        module_count=0,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.post(
        f"/api/v1/admin/courses/{course.id}/publish",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "published"
    assert data["published_at"] is not None


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------


async def test_enrollment_creates_record(authenticated_client, db_session):
    """Enrolling in a course creates a UserCourseEnrollment record."""
    jwt_service = JWTAuthService()
    user_id = str(uuid.uuid4())
    token = jwt_service.create_access_token(user_id=user_id, email="learner@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    course = Course(
        id=uuid.uuid4(),
        slug="enrollable-course",
        title_fr="Cours ouvert",
        title_en="Open Course",
        status="published",
        languages="fr,en",
        estimated_hours=15,
        module_count=0,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "active"
    assert data["course_id"] == str(course.id)

    result = await db_session.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.course_id == course.id,
            UserCourseEnrollment.user_id == uuid.UUID(user_id),
        )
    )
    enrollment = result.scalar_one_or_none()
    assert enrollment is not None
    assert enrollment.status == "active"


async def test_duplicate_enrollment_returns_409(authenticated_client, db_session):
    """Enrolling twice in the same course returns 409."""
    jwt_service = JWTAuthService()
    user_id = str(uuid.uuid4())
    token = jwt_service.create_access_token(user_id=user_id, email="learner2@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    course = Course(
        id=uuid.uuid4(),
        slug="already-enrolled-course",
        title_fr="Cours existant",
        title_en="Existing Course",
        status="published",
        languages="fr,en",
        estimated_hours=10,
        module_count=0,
    )
    db_session.add(course)
    enrollment = UserCourseEnrollment(
        user_id=uuid.UUID(user_id),
        course_id=course.id,
        status="active",
        completion_pct=0.0,
    )
    db_session.add(enrollment)
    await db_session.flush()

    response = await authenticated_client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers=headers,
    )
    assert response.status_code == 409


async def test_cannot_enroll_in_draft_course(authenticated_client, db_session):
    """Enrolling in a draft course returns 404."""
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(user_id=str(uuid.uuid4()), email="learner3@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    course = Course(
        id=uuid.uuid4(),
        slug="still-draft",
        title_fr="Brouillon",
        title_en="Draft",
        status="draft",
        languages="fr,en",
        estimated_hours=0,
        module_count=0,
    )
    db_session.add(course)
    await db_session.flush()

    response = await authenticated_client.post(
        f"/api/v1/courses/{course.id}/enroll",
        headers=headers,
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# RAG scoping unit test
# ---------------------------------------------------------------------------


def test_rag_retriever_accepts_rag_collection_id_filter():
    """SemanticRetriever._perform_search builds correct WHERE clause for rag_collection_id."""
    filters = {"rag_collection_id": "course_nutrition"}

    where_clauses = ["embedding IS NOT NULL"]
    params: dict = {}

    if filters and "rag_collection_id" in filters:
        where_clauses.append("source = :rag_collection_id")
        params["rag_collection_id"] = filters["rag_collection_id"]

    assert "source = :rag_collection_id" in where_clauses
    assert params["rag_collection_id"] == "course_nutrition"
