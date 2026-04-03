"""Public course catalog and learner enrollment endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, get_optional_user
from app.api.v1.schemas.courses import CourseResponse, EnrollmentResponse
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.progress import UserModuleProgress

logger = get_logger(__name__)
router = APIRouter(prefix="/courses", tags=["Courses"])


def _course_to_response(c: Course) -> CourseResponse:
    return CourseResponse(
        id=str(c.id),
        slug=c.slug,
        title_fr=c.title_fr,
        title_en=c.title_en,
        description_fr=c.description_fr,
        description_en=c.description_en,
        domain=c.domain,
        target_audience=c.target_audience,
        languages=c.languages,
        estimated_hours=c.estimated_hours,
        module_count=c.module_count,
        status=c.status,
        cover_image_url=c.cover_image_url,
        created_by=str(c.created_by) if c.created_by else None,
        rag_collection_id=c.rag_collection_id,
        created_at=c.created_at.isoformat(),
        published_at=c.published_at.isoformat() if c.published_at else None,
    )


@router.get("", response_model=list[CourseResponse])
async def list_published_courses(
    domain: str | None = Query(None),
    search: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    _current_user: AuthenticatedUser | None = Depends(get_optional_user),
    db=Depends(get_db_session),
) -> list[CourseResponse]:
    """Browse published course catalog. Public (no auth required)."""
    try:
        stmt = select(Course).where(Course.status == "published")

        if domain:
            stmt = stmt.where(Course.domain.ilike(f"%{domain}%"))

        if search:
            pattern = f"%{search}%"
            stmt = stmt.where(Course.title_fr.ilike(pattern) | Course.title_en.ilike(pattern))

        stmt = stmt.order_by(Course.published_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        courses = result.scalars().all()
        return [_course_to_response(c) for c in courses]
    except Exception as e:
        logger.error("Failed to list published courses", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list courses",
        )


@router.get("/enrolled", response_model=list[dict])
async def list_enrolled_courses(
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> list[dict]:
    """List courses the current user is enrolled in."""
    try:
        stmt = (
            select(UserCourseEnrollment, Course)
            .join(Course, UserCourseEnrollment.course_id == Course.id)
            .where(UserCourseEnrollment.user_id == uuid.UUID(current_user.id))
            .where(UserCourseEnrollment.status == "active")
            .order_by(UserCourseEnrollment.enrolled_at.desc())
        )
        result = await db.execute(stmt)
        rows = result.all()

        return [
            {
                "enrollment": {
                    "user_id": str(enr.user_id),
                    "course_id": str(enr.course_id),
                    "enrolled_at": enr.enrolled_at.isoformat(),
                    "status": enr.status,
                    "completion_pct": enr.completion_pct,
                },
                "course": _course_to_response(course).model_dump(),
            }
            for enr, course in rows
        ]
    except Exception as e:
        logger.error("Failed to list enrolled courses", error=str(e), user_id=current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve enrolled courses",
        )


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course_detail(
    course_id: uuid.UUID,
    _current_user: AuthenticatedUser | None = Depends(get_optional_user),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Get published course detail. Public."""
    result = await db.execute(
        select(Course).where(Course.id == course_id).where(Course.status == "published")
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return _course_to_response(course)


@router.post(
    "/{course_id}/enroll", response_model=EnrollmentResponse, status_code=status.HTTP_201_CREATED
)
async def enroll_in_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> EnrollmentResponse:
    """Enroll the current user in a published course. Creates module progress records."""
    result = await db.execute(
        select(Course).where(Course.id == course_id).where(Course.status == "published")
    )
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    user_uuid = uuid.UUID(current_user.id)

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
        existing_progress = await db.execute(
            select(UserModuleProgress).where(
                UserModuleProgress.user_id == user_uuid,
                UserModuleProgress.module_id == module.id,
            )
        )
        if not existing_progress.scalar_one_or_none():
            progress = UserModuleProgress(
                user_id=user_uuid,
                module_id=module.id,
                status="locked",
                completion_pct=0.0,
                time_spent_minutes=0,
            )
            db.add(progress)

    await db.commit()
    await db.refresh(enrollment)

    logger.info(
        "User enrolled in course",
        user_id=current_user.id,
        course_id=str(course_id),
        modules_initialized=len(modules),
    )

    return EnrollmentResponse(
        user_id=str(enrollment.user_id),
        course_id=str(enrollment.course_id),
        enrolled_at=enrollment.enrolled_at.isoformat(),
        status=enrollment.status,
        completion_pct=enrollment.completion_pct,
    )


@router.delete("/{course_id}/enroll", status_code=status.HTTP_204_NO_CONTENT)
async def unenroll_from_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db=Depends(get_db_session),
) -> None:
    """Unenroll (drop) from a course."""
    user_uuid = uuid.UUID(current_user.id)
    result = await db.execute(
        select(UserCourseEnrollment).where(
            UserCourseEnrollment.user_id == user_uuid,
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
