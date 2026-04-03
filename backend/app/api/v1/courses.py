"""Public course catalog and learner enrollment endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user, get_optional_user
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress

logger = get_logger(__name__)
router = APIRouter(prefix="/courses", tags=["Courses"])


class CourseListItem(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    domain: str | None
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


def _course_to_list_item(course: Course, enrolled: bool = False) -> CourseListItem:
    return CourseListItem(
        id=str(course.id),
        slug=course.slug,
        title_fr=course.title_fr,
        title_en=course.title_en,
        description_fr=course.description_fr,
        description_en=course.description_en,
        domain=course.domain,
        estimated_hours=course.estimated_hours,
        module_count=course.module_count,
        cover_image_url=course.cover_image_url,
        languages=course.languages,
        enrolled=enrolled,
    )


@router.get("", response_model=list[CourseListItem])
async def list_published_courses(
    domain: str | None = Query(None, description="Filter by domain"),
    search: str | None = Query(None, description="Search in title FR/EN"),
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> list[CourseListItem]:
    """Browse published courses. No auth required."""
    stmt = select(Course).where(Course.status == "published").order_by(Course.published_at.desc())

    if domain:
        stmt = stmt.where(Course.domain == domain)

    result = await db.execute(stmt)
    courses = result.scalars().all()

    if search:
        q = search.lower()
        courses = [
            c
            for c in courses
            if q in (c.title_fr or "").lower() or q in (c.title_en or "").lower()
        ]

    enrolled_ids: set[str] = set()
    if current_user:
        enroll_result = await db.execute(
            select(UserCourseEnrollment.course_id).where(
                UserCourseEnrollment.user_id == uuid.UUID(current_user.id),
                UserCourseEnrollment.status == "active",
            )
        )
        enrolled_ids = {str(row[0]) for row in enroll_result.all()}

    return [_course_to_list_item(c, enrolled=str(c.id) in enrolled_ids) for c in courses]


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
            & (UserCourseEnrollment.user_id == uuid.UUID(current_user.id))
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
        select(Course).where(Course.id == course_id, Course.status == "published")
    )
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found or not published",
        )

    existing_result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == uuid.UUID(current_user.id),
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
                UserModuleProgress.user_id == uuid.UUID(current_user.id),
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


@router.post("/{course_id}/unenroll", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_from_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    """Drop enrollment in a course."""
    result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == uuid.UUID(current_user.id),
            UserCourseEnrollment.course_id == course_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found"
        )

    enrollment.status = "dropped"
    await db.commit()
    logger.info("User unenrolled from course", user_id=current_user.id, course_id=str(course_id))
