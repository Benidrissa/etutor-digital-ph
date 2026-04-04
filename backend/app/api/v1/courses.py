"""Public course catalog and learner enrollment endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user, get_optional_user
from app.domain.models.course import (
    AudienceType,
    Course,
    CourseDomain,
    CourseLevel,
    UserCourseEnrollment,
)
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress

logger = get_logger(__name__)
router = APIRouter(prefix="/courses", tags=["Courses"])

# ---------------------------------------------------------------------------
# Taxonomy labels (bilingual)
# ---------------------------------------------------------------------------

DOMAIN_LABELS: dict[str, dict[str, str]] = {
    "health_sciences": {
        "label_fr": "Sciences de la sant\u00e9",
        "label_en": "Health Sciences",
    },
    "natural_sciences": {
        "label_fr": "Sciences naturelles",
        "label_en": "Natural Sciences",
    },
    "social_sciences": {
        "label_fr": "Sciences sociales",
        "label_en": "Social Sciences",
    },
    "mathematics": {
        "label_fr": "Math\u00e9matiques",
        "label_en": "Mathematics",
    },
    "engineering": {
        "label_fr": "Ing\u00e9nierie",
        "label_en": "Engineering",
    },
    "information_technology": {
        "label_fr": "Informatique",
        "label_en": "Information Technology",
    },
    "education": {
        "label_fr": "\u00c9ducation",
        "label_en": "Education",
    },
    "arts_humanities": {
        "label_fr": "Arts et lettres",
        "label_en": "Arts & Humanities",
    },
    "business_management": {
        "label_fr": "Gestion et commerce",
        "label_en": "Business & Management",
    },
    "law": {
        "label_fr": "Droit",
        "label_en": "Law",
    },
    "agriculture": {
        "label_fr": "Agriculture",
        "label_en": "Agriculture",
    },
    "environmental_studies": {
        "label_fr": "\u00c9tudes environnementales",
        "label_en": "Environmental Studies",
    },
    "other": {
        "label_fr": "Autre",
        "label_en": "Other",
    },
}

LEVEL_LABELS: dict[str, dict[str, str]] = {
    "beginner": {
        "label_fr": "D\u00e9butant",
        "label_en": "Beginner",
    },
    "intermediate": {
        "label_fr": "Interm\u00e9diaire",
        "label_en": "Intermediate",
    },
    "advanced": {
        "label_fr": "Avanc\u00e9",
        "label_en": "Advanced",
    },
    "expert": {
        "label_fr": "Expert",
        "label_en": "Expert",
    },
}

AUDIENCE_LABELS: dict[str, dict[str, str]] = {
    "kindergarten": {
        "label_fr": "Maternelle",
        "label_en": "Kindergarten",
    },
    "primary_school": {
        "label_fr": "Primaire",
        "label_en": "Primary School",
    },
    "secondary_school": {
        "label_fr": "Secondaire",
        "label_en": "Secondary School",
    },
    "university": {
        "label_fr": "Universitaire",
        "label_en": "University",
    },
    "professional": {
        "label_fr": "Professionnel",
        "label_en": "Professional",
    },
    "researcher": {
        "label_fr": "Chercheur",
        "label_en": "Researcher",
    },
    "teacher": {
        "label_fr": "Enseignant",
        "label_en": "Teacher",
    },
    "policy_maker": {
        "label_fr": "D\u00e9cideur politique",
        "label_en": "Policy Maker",
    },
    "continuing_education": {
        "label_fr": "Formation continue",
        "label_en": "Continuing Education",
    },
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CourseListItem(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    course_domain: list[str]
    course_level: list[str]
    audience_type: list[str]
    estimated_hours: int
    module_count: int
    cover_image_url: str | None
    languages: str
    enrolled: bool = False


class EnrollmentResponse(BaseModel):
    course_id: str
    user_id: str
    status: str
    enrolled_at: str
    completion_pct: float


def _course_to_list_item(
    course: Course, enrolled: bool = False
) -> CourseListItem:
    return CourseListItem(
        id=str(course.id),
        slug=course.slug,
        title_fr=course.title_fr,
        title_en=course.title_en,
        description_fr=course.description_fr,
        description_en=course.description_en,
        course_domain=list(course.course_domain or []),
        course_level=list(course.course_level or []),
        audience_type=list(course.audience_type or []),
        estimated_hours=course.estimated_hours,
        module_count=course.module_count,
        cover_image_url=course.cover_image_url,
        languages=course.languages,
        enrolled=enrolled,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/taxonomy")
async def get_taxonomy() -> dict:
    """Return valid taxonomy values with bilingual labels. No auth."""
    def _to_list(labels: dict[str, dict[str, str]]) -> list[dict]:
        return [
            {"value": k, **v} for k, v in labels.items()
        ]

    return {
        "domains": _to_list(DOMAIN_LABELS),
        "levels": _to_list(LEVEL_LABELS),
        "audience_types": _to_list(AUDIENCE_LABELS),
    }


@router.get("", response_model=list[CourseListItem])
async def list_published_courses(
    course_domain: str | None = Query(
        None, description="Filter by domain (enum value)"
    ),
    course_level: str | None = Query(
        None, description="Filter by level (enum value)"
    ),
    audience_type: str | None = Query(
        None, description="Filter by audience type (enum value)"
    ),
    search: str | None = Query(
        None, description="Search in title FR/EN"
    ),
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> list[CourseListItem]:
    """Browse published courses. No auth required."""
    stmt = (
        select(Course)
        .where(Course.status == "published")
        .order_by(Course.published_at.desc())
    )

    if course_domain:
        stmt = stmt.where(
            Course.course_domain.any(course_domain)
        )
    if course_level:
        stmt = stmt.where(
            Course.course_level.any(course_level)
        )
    if audience_type:
        stmt = stmt.where(
            Course.audience_type.any(audience_type)
        )

    result = await db.execute(stmt)
    courses = result.scalars().all()

    if search:
        q = search.lower()
        courses = [
            c
            for c in courses
            if q in (c.title_fr or "").lower()
            or q in (c.title_en or "").lower()
        ]

    enrolled_ids: set[str] = set()
    if current_user:
        enroll_result = await db.execute(
            select(UserCourseEnrollment.course_id).where(
                UserCourseEnrollment.user_id
                == uuid.UUID(current_user.id),
                UserCourseEnrollment.status == "active",
            )
        )
        enrolled_ids = {str(row[0]) for row in enroll_result.all()}

    return [
        _course_to_list_item(c, enrolled=str(c.id) in enrolled_ids)
        for c in courses
    ]


@router.get("/my-enrollments", response_model=list[CourseListItem])
async def my_enrollments(
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[CourseListItem]:
    """Get courses the current user is enrolled in."""
    result = await db.execute(
        select(Course)
        .join(
            UserCourseEnrollment,
            (UserCourseEnrollment.course_id == Course.id)
            & (
                UserCourseEnrollment.user_id
                == uuid.UUID(current_user.id)
            )
            & (UserCourseEnrollment.status == "active"),
        )
        .order_by(UserCourseEnrollment.enrolled_at.desc())
    )
    courses = result.scalars().all()
    return [_course_to_list_item(c, enrolled=True) for c in courses]


@router.post("/{course_id}/enroll", response_model=EnrollmentResponse)
async def enroll_in_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> EnrollmentResponse:
    """Enroll the current user in a published course."""
    course_result = await db.execute(
        select(Course).where(
            Course.id == course_id, Course.status == "published"
        )
    )
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found or not published",
        )

    existing_result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id
            == uuid.UUID(current_user.id),
            UserCourseEnrollment.course_id == course_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        if existing.status != "active":
            existing.status = "active"
            await db.commit()
            await db.refresh(existing)
        return EnrollmentResponse(
            course_id=str(existing.course_id),
            user_id=str(existing.user_id),
            status=existing.status,
            enrolled_at=existing.enrolled_at.isoformat(),
            completion_pct=existing.completion_pct,
        )

    enrollment = UserCourseEnrollment(
        user_id=uuid.UUID(current_user.id),
        course_id=course_id,
        status="active",
        completion_pct=0.0,
    )
    db.add(enrollment)

    modules_result = await db.execute(
        select(Module).where(Module.course_id == course_id)
    )
    modules = modules_result.scalars().all()
    for module in modules:
        prog_result = await db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id
                == uuid.UUID(current_user.id),
                UserModuleProgress.module_id == module.id,
            )
        )
        if prog_result.scalar_one_or_none() is None:
            db.add(
                UserModuleProgress(
                    user_id=uuid.UUID(current_user.id),
                    module_id=module.id,
                    status="locked",
                    completion_pct=0.0,
                    time_spent_minutes=0,
                )
            )

    await db.commit()
    await db.refresh(enrollment)

    logger.info(
        "User enrolled in course",
        user_id=current_user.id,
        course_id=str(course_id),
    )
    return EnrollmentResponse(
        course_id=str(enrollment.course_id),
        user_id=str(enrollment.user_id),
        status=enrollment.status,
        enrolled_at=enrollment.enrolled_at.isoformat(),
        completion_pct=enrollment.completion_pct,
    )


@router.post(
    "/{course_id}/unenroll",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unenroll_from_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    """Drop enrollment in a course."""
    result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id
            == uuid.UUID(current_user.id),
            UserCourseEnrollment.course_id == course_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Enrollment not found",
        )

    enrollment.status = "dropped"
    await db.commit()
    logger.info(
        "User unenrolled from course",
        user_id=current_user.id,
        course_id=str(course_id),
    )
