"""Admin course management endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.api.v1.schemas.courses import (
    AgentGenerateRequest,
    CourseCreateRequest,
    CourseListResponse,
    CourseResponse,
    CourseUpdateRequest,
    ModuleDraftResponse,
)
from app.domain.models.course import Course
from app.domain.models.module import Module
from app.domain.models.user import UserRole
from app.domain.services.course_agent_service import CourseAgentService

logger = structlog.get_logger()
router = APIRouter(prefix="/admin/courses", tags=["admin-courses"])


@router.get("/", response_model=CourseListResponse)
async def list_courses(
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseListResponse:
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    courses = result.scalars().all()
    return CourseListResponse(
        courses=[CourseResponse.model_validate(c) for c in courses],
        total=len(courses),
    )


@router.post("/", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    payload: CourseCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseResponse:
    existing = await db.execute(select(Course).where(Course.slug == payload.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A course with this slug already exists",
        )

    rag_collection_id = f"course_{payload.slug}"
    course = Course(
        id=uuid.uuid4(),
        slug=payload.slug,
        title_fr=payload.title_fr,
        title_en=payload.title_en,
        description_fr=payload.description_fr,
        description_en=payload.description_en,
        domain=payload.domain,
        target_audience=payload.target_audience,
        languages=payload.languages,
        estimated_hours=payload.estimated_hours,
        cover_image_url=payload.cover_image_url,
        created_by=uuid.UUID(current_user.id),
        rag_collection_id=rag_collection_id,
        status="draft",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    logger.info(
        "Course created",
        course_id=str(course.id),
        slug=course.slug,
        admin=current_user.email,
    )
    return CourseResponse.model_validate(course)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseResponse:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return CourseResponse.model_validate(course)


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: uuid.UUID,
    payload: CourseUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseResponse:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(course, field, value)

    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseResponse:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if course.status == "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Course is already published"
        )

    course.status = "published"
    course.published_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(course)
    logger.info("Course published", course_id=str(course_id), admin=current_user.email)
    return CourseResponse.model_validate(course)


@router.post("/{course_id}/archive", response_model=CourseResponse)
async def archive_course(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> CourseResponse:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    course.status = "archived"
    await db.commit()
    await db.refresh(course)
    return CourseResponse.model_validate(course)


@router.post("/{course_id}/generate-structure", response_model=list[ModuleDraftResponse])
async def generate_course_structure(
    course_id: uuid.UUID,
    payload: AgentGenerateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> list[ModuleDraftResponse]:
    """Use the content creator agent to generate a course module structure."""
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    agent = CourseAgentService()
    try:
        module_drafts = await agent.generate_course_structure(
            course=course,
            domain=payload.domain,
            target_audience=payload.target_audience,
            languages=payload.languages,
            source_documents=payload.source_documents,
        )
    except Exception as e:
        logger.error("Course structure generation failed", course_id=str(course_id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate course structure",
        )

    return [ModuleDraftResponse(**m) for m in module_drafts]


@router.get("/{course_id}/modules", response_model=list[dict])
async def list_course_modules(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
) -> list[dict]:
    result = await db.execute(
        select(Module).where(Module.course_id == course_id).order_by(Module.module_number)
    )
    modules = result.scalars().all()
    return [
        {
            "id": str(m.id),
            "module_number": m.module_number,
            "title_fr": m.title_fr,
            "title_en": m.title_en,
            "description_fr": m.description_fr,
            "description_en": m.description_en,
            "estimated_hours": m.estimated_hours,
            "bloom_level": m.bloom_level,
        }
        for m in modules
    ]
