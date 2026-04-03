"""Public course catalog and learner enrollment endpoints."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, verify_access_token
from app.api.v1.schemas.courses import (
    CourseListResponse,
    CourseResponse,
    EnrollmentResponse,
)
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress

logger = structlog.get_logger()
router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("/", response_model=CourseListResponse)
async def browse_catalog(
    domain: str | None = Query(default=None, description="Filter by domain"),
    search: str | None = Query(default=None, description="Search in title/description"),
    db: AsyncSession = Depends(get_db),
) -> CourseListResponse:
    """Browse published courses. No authentication required."""
    stmt = select(Course).where(Course.status == "published")
    if domain:
        stmt = stmt.where(Course.domain == domain)
    stmt = stmt.order_by(Course.published_at.desc())

    result = await db.execute(stmt)
    courses = result.scalars().all()

    if search:
        search_lower = search.lower()
        courses = [
            c
            for c in courses
            if search_lower in (c.title_fr or "").lower()
            or search_lower in (c.title_en or "").lower()
            or search_lower in (c.description_fr or "").lower()
            or search_lower in (c.description_en or "").lower()
        ]

    return CourseListResponse(
        courses=[CourseResponse.model_validate(c) for c in courses],
        total=len(courses),
    )


@router.get("/enrolled", response_model=list[dict])
async def my_enrollments(
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_access_token),
) -> list[dict]:
    """List courses the current user is enrolled in, with progress."""
    result = await db.execute(
        select(UserCourseEnrollment, Course)
        .join(Course, UserCourseEnrollment.course_id == Course.id)
        .where(UserCourseEnrollment.user_id == uuid.UUID(user.id))
        .where(UserCourseEnrollment.status == "active")
        .order_by(UserCourseEnrollment.enrolled_at.desc())
    )
    rows = result.all()

    enrollments = []
    for enrollment, course in rows:
        enrollments.append(
            {
                "course": CourseResponse.model_validate(course).model_dump(),
                "enrolled_at": enrollment.enrolled_at.isoformat(),
                "status": enrollment.status,
                "completion_pct": enrollment.completion_pct,
            }
        )
    return enrollments


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course_detail(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CourseResponse:
    """Get a published course by ID. No authentication required."""
    course = await db.get(Course, course_id)
    if not course or course.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return CourseResponse.model_validate(course)


@router.post(
    "/{course_id}/enroll", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED
)
async def enroll_in_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_access_token),
) -> EnrollmentResponse:
    """Enroll the current user in a published course."""
    course = await db.get(Course, course_id)
    if not course or course.status != "published":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    user_uuid = uuid.UUID(user.id)

    existing = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == user_uuid,
            UserCourseEnrollment.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already enrolled in this course",
        )

    enrollment = UserCourseEnrollment(
        user_id=user_uuid,
        course_id=course_id,
        status="active",
        completion_pct=0.0,
    )
    db.add(enrollment)

    modules_result = await db.execute(select(Module).where(Module.course_id == course_id))
    modules = modules_result.scalars().all()

    for module in modules:
        progress_check = await db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_uuid,
                UserModuleProgress.module_id == module.id,
            )
        )
        if not progress_check.scalar_one_or_none():
            progress = UserModuleProgress(
                user_id=user_uuid,
                module_id=module.id,
                status="locked",
                completion_pct=0.0,
            )
            db.add(progress)

    await db.commit()
    await db.refresh(enrollment)

    logger.info(
        "User enrolled in course",
        user_id=user.id,
        course_id=str(course_id),
        modules_initialized=len(modules),
    )
    return EnrollmentResponse.model_validate(enrollment)


@router.delete("/{course_id}/enroll", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_from_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: AuthenticatedUser = Depends(verify_access_token),
) -> None:
    """Drop enrollment from a course."""
    user_uuid = uuid.UUID(user.id)
    result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == user_uuid,
            UserCourseEnrollment.course_id == course_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enrollment not found")

    enrollment.status = "dropped"
    await db.commit()
    logger.info("User dropped course", user_id=user.id, course_id=str(course_id))
