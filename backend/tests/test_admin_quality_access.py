"""Role + owner gating for the Quality Agent admin/review endpoints (#2249).

Verifies that ``admin``, ``sub_admin``, and ``expert`` (only on owned
courses) can reach the quality endpoints, and that ``user`` cannot.
The Celery-dispatching paths (``POST .../runs``, regenerate) are
covered by gating tests only — actual task execution is exercised
elsewhere.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db, get_db_session
from app.domain.models.content import GeneratedContent
from app.domain.models.course import Course
from app.domain.models.course_quality import (
    CourseGlossaryTerm,
    CourseQualityRun,
    UnitQualityAssessment,
)
from app.domain.models.module import Module
from app.domain.models.user import User, UserRole
from app.domain.services.jwt_auth_service import JWTAuthService
from app.main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headers(user_id: uuid.UUID, role: str, email: str = "tester@example.com") -> dict[str, str]:
    """Mint a JWT for the given user_id+role and wrap it as a Bearer header."""
    token = JWTAuthService().create_access_token(
        user_id=str(user_id),
        email=email,
        role=role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def http_client(db_session):
    """AsyncClient with the request DB overridden to the test session."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def seeded(db_session):
    """Seed an admin, expert-owner, expert-other, learner, and one course owned by expert.

    Returns a SimpleNamespace-like dict so tests can pull what they need.
    """
    admin = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        name="Admin",
        role=UserRole.admin,
    )
    sub_admin = User(
        id=uuid.uuid4(),
        email="subadmin@example.com",
        name="Sub-Admin",
        role=UserRole.sub_admin,
    )
    expert_owner = User(
        id=uuid.uuid4(),
        email="expert.owner@example.com",
        name="Expert Owner",
        role=UserRole.expert,
    )
    expert_other = User(
        id=uuid.uuid4(),
        email="expert.other@example.com",
        name="Expert Other",
        role=UserRole.expert,
    )
    learner = User(
        id=uuid.uuid4(),
        email="learner@example.com",
        name="Learner",
        role=UserRole.user,
    )
    db_session.add_all([admin, sub_admin, expert_owner, expert_other, learner])
    await db_session.flush()

    owned_course = Course(
        id=uuid.uuid4(),
        slug=f"owned-course-{uuid.uuid4().hex[:8]}",
        title_fr="Cours Possédé",
        title_en="Owned Course",
        created_by=expert_owner.id,
    )
    other_course = Course(
        id=uuid.uuid4(),
        slug=f"other-course-{uuid.uuid4().hex[:8]}",
        title_fr="Autre Cours",
        title_en="Other Course",
        created_by=admin.id,
    )
    db_session.add_all([owned_course, other_course])
    await db_session.flush()

    # Seed a module + a flagged unit on the owned course so review-queue
    # surfaces it under the default has_issues filter.
    module = Module(
        id=uuid.uuid4(),
        module_number=1,
        level=1,
        title_fr="M1",
        title_en="M1",
        course_id=owned_course.id,
    )
    db_session.add(module)
    await db_session.flush()

    gc = GeneratedContent(
        id=uuid.uuid4(),
        module_id=module.id,
        content_type="lesson",
        language="fr",
        level=1,
        content={},
        quality_status="needs_review",
        quality_flags=[
            {
                "category": "terminology_drift",
                "severity": "high",
                "location": "concepts[0]",
                "description": "Term used inconsistently",
                "evidence": "épidémiologie",
                "suggested_fix": "Use canonical term as defined in glossary.",
                "evidence_unit_id": None,
            }
        ],
        regeneration_attempts=0,
        is_manually_edited=False,
        validated=False,
    )
    db_session.add(gc)

    # A glossary drift on the owned course
    drift_term = CourseGlossaryTerm(
        course_id=owned_course.id,
        term_normalized="x",
        term_display="X",
        language="fr",
        canonical_definition="Definition.",
        consistency_status="drift_detected",
        drift_details="Two definitions found.",
    )
    db_session.add(drift_term)

    # A completed run with one assessment so the unit-detail endpoint
    # has dimension scores to return.
    run = CourseQualityRun(
        id=uuid.uuid4(),
        course_id=owned_course.id,
        run_kind="full",
        status="completed",
        triggered_by_user_id=admin.id,
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        budget_credits=200,
        spent_credits=12,
    )
    db_session.add(run)
    await db_session.flush()

    assessment = UnitQualityAssessment(
        run_id=run.id,
        generated_content_id=gc.id,
        attempt_number=1,
        score=72,
        dimension_scores={
            "terminology_consistency": 60,
            "source_grounding": 80,
            "syllabus_alignment": 80,
            "internal_contradictions": 70,
            "pedagogical_fit": 75,
            "structural_completeness": 75,
        },
        flags=[],
        model="claude-sonnet-4-6",
    )
    db_session.add(assessment)
    await db_session.commit()

    return {
        "admin": admin,
        "sub_admin": sub_admin,
        "expert_owner": expert_owner,
        "expert_other": expert_other,
        "learner": learner,
        "owned_course": owned_course,
        "other_course": other_course,
        "module": module,
        "gc": gc,
        "run": run,
    }


# ---------------------------------------------------------------------------
# /admin/quality/review-queue (cross-course)
# ---------------------------------------------------------------------------


async def test_review_queue_admin_sees_all_courses_with_issues(http_client, seeded):
    headers = _headers(seeded["admin"].id, "admin")
    r = await http_client.get("/api/v1/admin/quality/review-queue", headers=headers)
    assert r.status_code == 200
    data = r.json()
    course_ids = {row["course_id"] for row in data}
    assert str(seeded["owned_course"].id) in course_ids
    # other_course has no flagged units, so default has_issues=true filters it out
    assert str(seeded["other_course"].id) not in course_ids


async def test_review_queue_admin_with_has_issues_false_includes_clean_courses(
    http_client, seeded
):
    headers = _headers(seeded["admin"].id, "admin")
    r = await http_client.get(
        "/api/v1/admin/quality/review-queue?has_issues=false", headers=headers
    )
    assert r.status_code == 200
    course_ids = {row["course_id"] for row in r.json()}
    assert str(seeded["owned_course"].id) in course_ids
    assert str(seeded["other_course"].id) in course_ids


async def test_review_queue_expert_only_sees_own_courses(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.get("/api/v1/admin/quality/review-queue", headers=headers)
    assert r.status_code == 200
    course_ids = {row["course_id"] for row in r.json()}
    assert str(seeded["owned_course"].id) in course_ids
    assert str(seeded["other_course"].id) not in course_ids


async def test_review_queue_other_expert_sees_empty(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.get("/api/v1/admin/quality/review-queue", headers=headers)
    assert r.status_code == 200
    assert r.json() == []


async def test_review_queue_learner_forbidden(http_client, seeded):
    headers = _headers(seeded["learner"].id, "user")
    r = await http_client.get("/api/v1/admin/quality/review-queue", headers=headers)
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Per-course endpoints — owner gating
# ---------------------------------------------------------------------------


async def test_summary_admin_any_course(http_client, seeded):
    headers = _headers(seeded["admin"].id, "admin")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/summary",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["units_total"] == 1
    assert body["glossary_drift_count"] == 1


async def test_summary_sub_admin_any_course(http_client, seeded):
    headers = _headers(seeded["sub_admin"].id, "sub_admin")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/summary",
        headers=headers,
    )
    assert r.status_code == 200


async def test_summary_expert_owner(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/summary",
        headers=headers,
    )
    assert r.status_code == 200


async def test_summary_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/summary",
        headers=headers,
    )
    assert r.status_code == 403


async def test_summary_learner_forbidden(http_client, seeded):
    headers = _headers(seeded["learner"].id, "user")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/summary",
        headers=headers,
    )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Per-unit drill-in (#2249 new endpoint)
# ---------------------------------------------------------------------------


async def test_unit_quality_detail_admin(http_client, seeded):
    headers = _headers(seeded["admin"].id, "admin")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["generated_content_id"] == str(seeded["gc"].id)
    assert body["quality_status"] == "needs_review"
    # dimension_scores comes from the latest UnitQualityAssessment
    assert body["dimension_scores"] is not None
    assert body["dimension_scores"]["terminology_consistency"] == 60
    # quality_flags comes from GeneratedContent.quality_flags JSONB
    assert body["flag_count"] == 1
    assert body["quality_flags"][0]["category"] == "terminology_drift"


async def test_unit_quality_detail_expert_owner(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality",
        headers=headers,
    )
    assert r.status_code == 200


async def test_unit_quality_detail_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality",
        headers=headers,
    )
    assert r.status_code == 403


async def test_unit_quality_detail_missing_course(http_client, seeded):
    headers = _headers(seeded["admin"].id, "admin")
    r = await http_client.get(
        f"/api/v1/admin/courses/{uuid.uuid4()}/units/{seeded['gc'].id}/quality",
        headers=headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Override actions — gating only (Celery dispatch is exercised elsewhere)
# ---------------------------------------------------------------------------


async def test_resolve_unit_expert_owner(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.post(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality/resolve",
        headers=headers,
        json={"note": "Reviewed and accepted"},
    )
    assert r.status_code == 200
    assert r.json()["quality_status"] == "passing"


async def test_resolve_unit_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.post(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality/resolve",
        headers=headers,
        json={"note": None},
    )
    assert r.status_code == 403


async def test_unlock_unit_expert_owner(http_client, seeded, db_session):
    # Lock the row first
    seeded["gc"].is_manually_edited = True
    await db_session.commit()

    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.post(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality/unlock",
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["is_manually_edited"] is False


async def test_unlock_unit_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.post(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/units/"
        f"{seeded['gc'].id}/quality/unlock",
        headers=headers,
    )
    assert r.status_code == 403


async def test_glossary_expert_owner(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/glossary",
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["consistency_status"] == "drift_detected"


async def test_glossary_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/glossary",
        headers=headers,
    )
    assert r.status_code == 403


async def test_runs_list_expert_owner(http_client, seeded):
    headers = _headers(seeded["expert_owner"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/runs",
        headers=headers,
    )
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["id"] == str(seeded["run"].id)


async def test_run_detail_expert_non_owner_forbidden(http_client, seeded):
    headers = _headers(seeded["expert_other"].id, "expert")
    r = await http_client.get(
        f"/api/v1/admin/courses/{seeded['owned_course'].id}/quality/runs/"
        f"{seeded['run'].id}",
        headers=headers,
    )
    assert r.status_code == 403
