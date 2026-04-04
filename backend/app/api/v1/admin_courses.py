"""Admin endpoints for course management (CRUD, publish, RAG indexation)."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.user import UserRole
from app.domain.services.course_management_service import CourseManagementService
from app.tasks.rag_indexation import UPLOAD_DIR

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/courses", tags=["Admin - Courses"])

_svc = CourseManagementService()


class CreateCourseRequest(BaseModel):
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    course_domain: list[str] = []
    course_level: list[str] = []
    audience_type: list[str] = []
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
    course_domain: list[str]
    course_level: list[str]
    audience_type: list[str]
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
        course_domain=list(course.course_domain or []),
        course_level=list(course.course_level or []),
        audience_type=list(course.audience_type or []),
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
    course = await _svc.create_course(
        db=db,
        actor_id=uuid.UUID(current_user.id),
        data=request.model_dump(),
    )
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
    course = await _svc.update_course(
        db=db,
        course_id=course_id,
        data=request.model_dump(exclude_unset=True),
        actor_id=uuid.UUID(current_user.id),
        check_ownership=False,
    )
    return _course_to_response(course)


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Publish a draft course. Admin only."""
    course = await _svc.publish_course(
        db=db,
        course_id=course_id,
        actor_id=uuid.UUID(current_user.id),
        check_ownership=False,
    )
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
    result = await _svc.generate_structure(
        db=db,
        course_id=course_id,
        actor_id=uuid.UUID(current_user.id),
        estimated_hours=request.estimated_hours,
        deduct_credits=False,
    )
    logger.info(
        "Course structure generated and saved",
        course_id=str(course_id),
        module_count=result["count"],
    )
    return result


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


# ---------------------------------------------------------------------------
# RAG Indexation
# ---------------------------------------------------------------------------


@router.post("/{course_id}/index-resources")
async def trigger_rag_indexation(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Trigger RAG indexation for course resources. Returns Celery task ID."""
    result = await _svc.index_resources(
        db=db,
        course_id=course_id,
        actor_id=uuid.UUID(current_user.id),
        check_ownership=False,
        deduct_credits=False,
    )
    logger.info(
        "RAG indexation triggered",
        course_id=str(course_id),
        task_id=result["task_id"],
        admin_id=current_user.id,
    )
    return result


@router.get("/{course_id}/index-status")
async def get_rag_index_status(
    course_id: uuid.UUID,
    task_id: str | None = None,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Get RAG indexation status for a course."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    chunk_count = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.source == course.rag_collection_id)
    )
    chunks_indexed = chunk_count.scalar_one()

    response = {
        "course_id": str(course_id),
        "rag_collection_id": course.rag_collection_id,
        "chunks_indexed": chunks_indexed,
        "indexed": chunks_indexed > 0,
    }

    if task_id:
        task_result = AsyncResult(task_id)
        response["task"] = {
            "id": task_id,
            "state": task_result.state,
            "meta": task_result.info if isinstance(task_result.info, dict) else {},
        }

    return response


# ---------------------------------------------------------------------------
# Resource Upload
# ---------------------------------------------------------------------------


@router.get("/{course_id}/resources")
async def list_course_resources(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """List uploaded resource files for a course."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    course_dir = UPLOAD_DIR / str(course_id)
    if not course_dir.exists():
        return {"course_id": str(course_id), "files": []}

    files = []
    for f in sorted(course_dir.glob("*.pdf")):
        stat = f.stat()
        files.append(
            {
                "name": f.name,
                "size_bytes": stat.st_size,
                "uploaded_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )

    return {"course_id": str(course_id), "files": files}


@router.post("/{course_id}/resources", status_code=status.HTTP_201_CREATED)
async def upload_course_resource(
    course_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> dict:
    """Upload a PDF resource for a course. Stored in uploads/course_resources/{course_id}/."""
    return await _svc.upload_resource(
        db=db,
        course_id=course_id,
        file=file,
        actor_id=uuid.UUID(current_user.id),
        check_ownership=False,
    )


@router.delete("/{course_id}/resources/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course_resource(
    course_id: uuid.UUID,
    filename: str,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete an uploaded resource file from a course."""
    import re as _re

    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    safe_name = _re.sub(r"[^\w.\-]", "_", Path(filename).name)
    file_path = UPLOAD_DIR / str(course_id) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    file_path.unlink()
    logger.info(
        "Course resource deleted",
        course_id=str(course_id),
        filename=safe_name,
        admin_id=current_user.id,
    )
