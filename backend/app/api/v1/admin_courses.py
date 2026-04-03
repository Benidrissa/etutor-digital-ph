"""Admin endpoints for multi-course management."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.api.v1.schemas.courses import (
    AgentGenerateRequest,
    CourseCreateRequest,
    CourseResponse,
    CourseUpdateRequest,
)
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.user import UserRole
from app.domain.services.course_agent_service import CourseAgentService

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/courses", tags=["Admin — Courses"])


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
async def list_all_courses(
    status_filter: str | None = Query(None, alias="status"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[CourseResponse]:
    """List all courses (all statuses). Admin only."""
    try:
        stmt = select(Course)
        if status_filter:
            stmt = stmt.where(Course.status == status_filter)
        stmt = stmt.order_by(Course.created_at.desc()).offset(offset).limit(limit)
        result = await db.execute(stmt)
        courses = result.scalars().all()
        return [_course_to_response(c) for c in courses]
    except Exception as e:
        logger.error("Failed to list courses", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list courses",
        )


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    req: CourseCreateRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Create a new course (draft). Admin only."""
    existing = await db.execute(select(Course).where(Course.slug == req.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Course with slug '{req.slug}' already exists",
        )

    course = Course(
        id=uuid.uuid4(),
        slug=req.slug,
        title_fr=req.title_fr,
        title_en=req.title_en,
        description_fr=req.description_fr,
        description_en=req.description_en,
        domain=req.domain,
        target_audience=req.target_audience,
        languages=req.languages,
        estimated_hours=req.estimated_hours,
        cover_image_url=req.cover_image_url,
        created_by=uuid.UUID(current_user.id),
        status="draft",
        rag_collection_id=f"course_{req.slug}",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)
    logger.info("Course created", course_id=str(course.id), admin_id=current_user.id)
    return _course_to_response(course)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Get course detail. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return _course_to_response(course)


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: uuid.UUID,
    req: CourseUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Update course metadata. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    for field, value in req.model_dump(exclude_none=True).items():
        setattr(course, field, value)

    await db.commit()
    await db.refresh(course)
    return _course_to_response(course)


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Publish a course. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    module_count_result = await db.execute(
        select(func.count()).select_from(Module).where(Module.course_id == course_id)
    )
    module_count = module_count_result.scalar_one()

    course.status = "published"
    course.published_at = datetime.now(UTC)
    course.module_count = module_count

    await db.commit()
    await db.refresh(course)
    logger.info("Course published", course_id=str(course_id), admin_id=current_user.id)
    return _course_to_response(course)


@router.post("/{course_id}/archive", response_model=CourseResponse)
async def archive_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Archive a course. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    course.status = "archived"
    await db.commit()
    await db.refresh(course)
    logger.info("Course archived", course_id=str(course_id), admin_id=current_user.id)
    return _course_to_response(course)


@router.post("/{course_id}/generate-structure")
async def generate_course_structure(
    course_id: uuid.UUID,
    req: AgentGenerateRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Use AI agent to generate course module structure. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    agent = CourseAgentService()
    modules = await agent.generate_course_structure(
        title_fr=course.title_fr,
        title_en=course.title_en,
        domain=req.domain,
        target_audience=req.target_audience or course.target_audience or "",
        description_fr=req.description_fr or course.description_fr,
        description_en=req.description_en or course.description_en,
    )

    logger.info(
        "Course structure generated",
        course_id=str(course_id),
        module_count=len(modules),
    )
    return {"course_id": str(course_id), "generated_modules": modules}
