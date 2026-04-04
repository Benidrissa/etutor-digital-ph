"""Admin endpoints for course management (CRUD, publish, agent-generate structure)."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.user import UserRole
from app.domain.services.course_agent_service import CourseAgentService

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/courses", tags=["Admin - Courses"])


class CreateCourseRequest(BaseModel):
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    domain: str | None = None
    target_audience: str | None = None
    languages: str = "fr,en"
    estimated_hours: int = 20
    cover_image_url: str | None = None
    rag_collection_id: str | None = None


class CourseResponse(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    domain: str | None
    target_audience: str | None
    languages: str
    estimated_hours: int
    module_count: int
    status: str
    cover_image_url: str | None
    created_by: str | None
    rag_collection_id: str | None
    created_at: str
    published_at: str | None


def _course_to_response(course: Course) -> CourseResponse:
    return CourseResponse(
        id=str(course.id),
        slug=course.slug,
        title_fr=course.title_fr,
        title_en=course.title_en,
        description_fr=course.description_fr,
        description_en=course.description_en,
        domain=course.domain,
        target_audience=course.target_audience,
        languages=course.languages,
        estimated_hours=course.estimated_hours,
        module_count=course.module_count,
        status=course.status,
        cover_image_url=course.cover_image_url,
        created_by=str(course.created_by) if course.created_by else None,
        rag_collection_id=course.rag_collection_id,
        created_at=course.created_at.isoformat(),
        published_at=course.published_at.isoformat() if course.published_at else None,
    )


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug


@router.get("", response_model=list[CourseResponse])
async def list_courses_admin(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> list[CourseResponse]:
    """List all courses (any status). Admin only."""
    result = await db.execute(select(Course).order_by(Course.created_at.desc()))
    courses = result.scalars().all()
    return [_course_to_response(c) for c in courses]


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    request: CreateCourseRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Create a new course (draft). Admin only."""
    base_slug = _slugify(request.title_en or request.title_fr)
    slug = base_slug
    suffix = 1
    while True:
        existing = await db.execute(select(Course).where(Course.slug == slug))
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    course = Course(
        id=uuid.uuid4(),
        slug=slug,
        title_fr=request.title_fr,
        title_en=request.title_en,
        description_fr=request.description_fr,
        description_en=request.description_en,
        domain=request.domain,
        target_audience=request.target_audience,
        languages=request.languages,
        estimated_hours=request.estimated_hours,
        cover_image_url=request.cover_image_url,
        rag_collection_id=request.rag_collection_id or str(uuid.uuid4()),
        created_by=uuid.UUID(current_user.id),
        status="draft",
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    logger.info("Course created", course_id=str(course.id), admin_id=current_user.id)
    return _course_to_response(course)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course_admin(
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
    request: CreateCourseRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Update course metadata. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(course, field, value)

    await db.commit()
    await db.refresh(course)
    return _course_to_response(course)


class IndexStatusResponse(BaseModel):
    course_id: str
    job_id: str | None
    state: str
    chunk_count: int | None
    progress_pct: float
    error_message: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None


class TriggerIndexResponse(BaseModel):
    job_id: str
    celery_task_id: str
    state: str
    message: str


async def _get_latest_index_job(db, course_id: uuid.UUID) -> dict | None:
    result = await db.execute(
        text(
            """
            SELECT id, celery_task_id, state, chunk_count, progress_pct,
                   error_message, created_at, updated_at, completed_at
            FROM rag_indexation_jobs
            WHERE course_id = :course_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"course_id": course_id},
    )
    row = result.mappings().one_or_none()
    return dict(row) if row else None


@router.post("/{course_id}/index-resources", response_model=TriggerIndexResponse)
async def trigger_rag_indexation(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> TriggerIndexResponse:
    """Trigger RAG indexation for all PDFs uploaded to this course. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    existing_job = await _get_latest_index_job(db, course_id)
    if existing_job and existing_job["state"] in ("pending", "extracting", "chunking", "embedding"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Indexation already in progress (state: {existing_job['state']}). "
            f"Job ID: {existing_job['id']}",
        )

    if not course.rag_collection_id:
        course.rag_collection_id = str(course_id)
        await db.commit()
        await db.refresh(course)

    job_id = str(uuid.uuid4())
    await db.execute(
        text(
            """
            INSERT INTO rag_indexation_jobs (id, course_id, state, progress_pct, created_at)
            VALUES (:id, :course_id, 'pending', 0.0, NOW())
            """
        ),
        {"id": uuid.UUID(job_id), "course_id": course_id},
    )
    await db.commit()

    from app.tasks.rag_indexation import index_course_resources

    task = index_course_resources.apply_async(
        args=[str(course_id), job_id],
        task_id=None,
    )

    await db.execute(
        text("UPDATE rag_indexation_jobs SET celery_task_id = :task_id WHERE id = :job_id"),
        {"task_id": task.id, "job_id": uuid.UUID(job_id)},
    )
    await db.commit()

    logger.info(
        "RAG indexation triggered",
        course_id=str(course_id),
        job_id=job_id,
        celery_task_id=task.id,
        admin_id=current_user.id,
    )
    return TriggerIndexResponse(
        job_id=job_id,
        celery_task_id=task.id,
        state="pending",
        message="RAG indexation started. Poll /index-status for progress.",
    )


@router.get("/{course_id}/index-status", response_model=IndexStatusResponse)
async def get_index_status(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> IndexStatusResponse:
    """Get RAG indexation progress for a course. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    job = await _get_latest_index_job(db, course_id)
    if not job:
        return IndexStatusResponse(
            course_id=str(course_id),
            job_id=None,
            state="not_started",
            chunk_count=None,
            progress_pct=0.0,
            error_message=None,
            created_at=None,
            updated_at=None,
            completed_at=None,
        )

    return IndexStatusResponse(
        course_id=str(course_id),
        job_id=str(job["id"]),
        state=job["state"],
        chunk_count=job["chunk_count"],
        progress_pct=float(job["progress_pct"]),
        error_message=job["error_message"],
        created_at=job["created_at"].isoformat() if job["created_at"] else None,
        updated_at=job["updated_at"].isoformat() if job["updated_at"] else None,
        completed_at=job["completed_at"].isoformat() if job["completed_at"] else None,
    )


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Publish a draft course. Blocked if RAG indexation is not complete. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    job = await _get_latest_index_job(db, course_id)
    if not job or job["state"] != "complete":
        current_state = job["state"] if job else "not_started"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot publish: RAG indexation must be complete before publishing. "
                f"Current state: '{current_state}'. "
                f"Trigger indexation via POST /admin/courses/{course_id}/index-resources first."
            ),
        )

    course.status = "published"
    course.published_at = datetime.now(UTC)

    module_count_result = await db.execute(
        select(func.count()).select_from(Module).where(Module.course_id == course_id)
    )
    course.module_count = module_count_result.scalar_one()

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


class GenerateStructureRequest(BaseModel):
    estimated_hours: int = 20
    target_audience: str | None = None


@router.post("/{course_id}/generate-structure")
async def generate_course_structure(
    course_id: uuid.UUID,
    request: GenerateStructureRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """
    Use content creator agent to generate module outline for a course.
    Saves generated modules to the database with course_id FK. Admin only.
    """
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    max_number_result = await db.execute(select(func.max(Module.module_number)))
    max_number = max_number_result.scalar_one() or 0

    agent = CourseAgentService()
    module_dicts = await agent.generate_course_structure(
        title_fr=course.title_fr,
        title_en=course.title_en,
        domain=course.domain,
        target_audience=request.target_audience or course.target_audience,
        estimated_hours=request.estimated_hours or course.estimated_hours,
    )

    saved_modules = []
    for i, m in enumerate(module_dicts):
        module = Module(
            id=uuid.uuid4(),
            module_number=max_number + i + 1,
            level=1,
            title_fr=m["title_fr"],
            title_en=m["title_en"],
            description_fr=m.get("description_fr"),
            description_en=m.get("description_en"),
            estimated_hours=m.get("estimated_hours", 20),
            bloom_level=m.get("bloom_level"),
            course_id=course_id,
        )
        db.add(module)
        saved_modules.append(
            {
                "id": str(module.id),
                "module_number": module.module_number,
                "title_fr": module.title_fr,
                "title_en": module.title_en,
            }
        )

    course.module_count = (
        await db.execute(
            select(func.count()).select_from(Module).where(Module.course_id == course_id)
        )
    ).scalar_one() + len(module_dicts)

    await db.commit()
    logger.info(
        "Course structure generated and saved",
        course_id=str(course_id),
        module_count=len(saved_modules),
    )
    return {"modules": saved_modules, "count": len(saved_modules)}


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete a draft course. Admin only. Cannot delete published courses."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if course.status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Archive the course before deleting",
        )

    enroll_result = await db.execute(
        select(func.count())
        .select_from(UserCourseEnrollment)
        .where(UserCourseEnrollment.course_id == course_id)
    )
    if enroll_result.scalar_one() > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete a course with enrolled learners",
        )

    await db.delete(course)
    await db.commit()
    logger.info("Course deleted", course_id=str(course_id), admin_id=current_user.id)
