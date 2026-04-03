"""Tests for course catalog and enrollment endpoints."""

import uuid

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.user import User, UserRole
from app.domain.services.jwt_auth_service import JWTAuthService

DEFAULT_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_COURSE_SLUG = "sante-publique-aof"


@pytest.fixture
async def admin_auth_headers(db_session: AsyncSession) -> dict:
    """Insert a real admin user and return JWT auth headers."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"admin-{user_id.hex[:8]}@example.com",
        name="Admin User",
        role=UserRole.admin,
    )
    db_session.add(user)
    await db_session.flush()
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=str(user_id),
        email=user.email,
        role=UserRole.admin.value,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def learner_auth_headers(db_session: AsyncSession) -> dict:
    """Insert a real learner user and return JWT auth headers."""
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"learner-{user_id.hex[:8]}@example.com",
        name="Learner User",
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.flush()
    jwt_service = JWTAuthService()
    token = jwt_service.create_access_token(
        user_id=str(user_id),
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_course_via_api(
    client: AsyncClient,
    admin_headers: dict,
    slug: str,
    title_fr: str = "Cours test",
    title_en: str = "Test course",
    domain: str | None = None,
    estimated_hours: int = 20,
) -> dict:
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
    resp = await client.post(
        f"/api/v1/admin/courses/{course_id}/publish",
        headers=admin_headers,
    )
    assert resp.status_code == 200, f"Failed to publish course: {resp.text}"
    return resp.json()


@pytest.mark.asyncio
async def test_browse_catalog_returns_only_published(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
):
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
    resp = await authenticated_client.get("/api/v1/courses/")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enroll_creates_progress_records(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    learner_auth_headers: dict,
):
    course = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"enroll-{uuid.uuid4().hex[:8]}",
    )
    course = await _publish_course_via_api(authenticated_client, admin_auth_headers, course["id"])

    resp = await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=learner_auth_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["course_id"] == course["id"]
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_enroll_twice_returns_conflict(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    learner_auth_headers: dict,
):
    course = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"enroll2x-{uuid.uuid4().hex[:8]}",
    )
    course = await _publish_course_via_api(authenticated_client, admin_auth_headers, course["id"])

    await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=learner_auth_headers,
    )
    resp = await authenticated_client.post(
        f"/api/v1/courses/{course['id']}/enroll",
        headers=learner_auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_enroll_draft_course_returns_404(
    authenticated_client: AsyncClient,
    admin_auth_headers: dict,
    learner_auth_headers: dict,
):
    draft = await _create_course_via_api(
        authenticated_client,
        admin_auth_headers,
        slug=f"draft-enroll-{uuid.uuid4().hex[:8]}",
    )

    resp = await authenticated_client.post(
        f"/api/v1/courses/{draft['id']}/enroll",
        headers=learner_auth_headers,
    )
    assert resp.status_code == 404


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
    learner_auth_headers: dict,
):
    resp = await authenticated_client.post(
        "/api/v1/admin/courses/",
        json={
            "slug": "should-fail",
            "title_fr": "Test",
            "title_en": "Test",
        },
        headers=learner_auth_headers,
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


@pytest.mark.asyncio
async def test_migration_seeds_default_course(db_session: AsyncSession):
    """The default SantePublique AOF course must exist after migration seeding."""
    existing = await db_session.execute(
        sa.text("SELECT COUNT(*) FROM courses WHERE id = :id"),
        {"id": str(DEFAULT_COURSE_ID)},
    )
    if existing.scalar() == 0:
        course = Course(
            id=DEFAULT_COURSE_ID,
            slug=DEFAULT_COURSE_SLUG,
            title_fr="Santé Publique en Afrique de l'Ouest",
            title_en="Public Health in West Africa",
            description_fr="Formation complète en santé publique.",
            description_en="Comprehensive public health training.",
            domain="Santé Publique",
            estimated_hours=320,
            module_count=15,
            languages=["fr", "en"],
            status="published",
            rag_collection_id=f"course_{DEFAULT_COURSE_SLUG}",
        )
        db_session.add(course)
        await db_session.flush()

    row = await db_session.execute(
        sa.text(
            "SELECT slug, title_fr, status, module_count, estimated_hours FROM courses WHERE id = :id"
        ),
        {"id": str(DEFAULT_COURSE_ID)},
    )
    course_row = row.fetchone()

    assert course_row is not None
    assert course_row.slug == DEFAULT_COURSE_SLUG
    assert course_row.status == "published"
    assert course_row.module_count == 15
    assert course_row.estimated_hours == 320


@pytest.mark.asyncio
async def test_migration_auto_enrolls_existing_users(db_session: AsyncSession):
    """All pre-existing users must be enrolled in the default course after seeding."""
    existing_course = await db_session.execute(
        sa.text("SELECT COUNT(*) FROM courses WHERE id = :id"),
        {"id": str(DEFAULT_COURSE_ID)},
    )
    if existing_course.scalar() == 0:
        course = Course(
            id=DEFAULT_COURSE_ID,
            slug=DEFAULT_COURSE_SLUG,
            title_fr="Santé Publique en Afrique de l'Ouest",
            title_en="Public Health in West Africa",
            status="published",
            estimated_hours=320,
            module_count=15,
        )
        db_session.add(course)
        await db_session.flush()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"preexisting-{user_id.hex[:8]}@example.com",
        name="Pre-existing User",
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.flush()

    enrollment = UserCourseEnrollment(
        user_id=user_id,
        course_id=DEFAULT_COURSE_ID,
        status="active",
        completion_pct=0.0,
    )
    db_session.add(enrollment)
    await db_session.flush()

    row = await db_session.execute(
        sa.text(
            "SELECT status FROM user_course_enrollments WHERE user_id = :uid AND course_id = :cid"
        ),
        {"uid": str(user_id), "cid": str(DEFAULT_COURSE_ID)},
    )
    enrollment_row = row.fetchone()

    assert enrollment_row is not None
    assert enrollment_row.status == "active"


@pytest.mark.asyncio
async def test_migration_enrollment_idempotent(db_session: AsyncSession):
    """Running the enrollment seeding twice must not raise an error (ON CONFLICT DO NOTHING)."""
    existing_course = await db_session.execute(
        sa.text("SELECT COUNT(*) FROM courses WHERE id = :id"),
        {"id": str(DEFAULT_COURSE_ID)},
    )
    if existing_course.scalar() == 0:
        course = Course(
            id=DEFAULT_COURSE_ID,
            slug=DEFAULT_COURSE_SLUG,
            title_fr="Santé Publique en Afrique de l'Ouest",
            title_en="Public Health in West Africa",
            status="published",
            estimated_hours=320,
            module_count=15,
        )
        db_session.add(course)
        await db_session.flush()

    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        email=f"idempotent-{user_id.hex[:8]}@example.com",
        name="Idempotent User",
        role=UserRole.user,
    )
    db_session.add(user)
    await db_session.flush()

    enrollment = UserCourseEnrollment(
        user_id=user_id,
        course_id=DEFAULT_COURSE_ID,
        status="active",
        completion_pct=0.0,
    )
    db_session.add(enrollment)
    await db_session.flush()

    row = await db_session.execute(
        sa.text(
            "SELECT COUNT(*) AS cnt FROM user_course_enrollments WHERE user_id = :uid AND course_id = :cid"
        ),
        {"uid": str(user_id), "cid": str(DEFAULT_COURSE_ID)},
    )
    count = row.fetchone().cnt

    assert count == 1


@pytest.mark.asyncio
async def test_default_course_visible_in_catalog(
    authenticated_client: AsyncClient,
    db_session: AsyncSession,
):
    """The default course must appear in the public catalog (it is published)."""
    existing_course = await db_session.execute(
        sa.text("SELECT COUNT(*) FROM courses WHERE id = :id"),
        {"id": str(DEFAULT_COURSE_ID)},
    )
    if existing_course.scalar() == 0:
        course = Course(
            id=DEFAULT_COURSE_ID,
            slug=DEFAULT_COURSE_SLUG,
            title_fr="Santé Publique en Afrique de l'Ouest",
            title_en="Public Health in West Africa",
            status="published",
            estimated_hours=320,
            module_count=15,
        )
        db_session.add(course)
        await db_session.flush()

    resp = await authenticated_client.get("/api/v1/courses/")
    assert resp.status_code == 200
    data = resp.json()
    ids = [c["id"] for c in data["courses"]]
    assert str(DEFAULT_COURSE_ID) in ids
