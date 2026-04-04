"""Admin endpoints for course management (CRUD, publish, RAG indexation)."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.document_chunk import DocumentChunk
from app.domain.models.module import Module
from app.domain.models.taxonomy import CourseTaxonomy, TaxonomyCategory
from app.domain.models.user import UserRole
from app.domain.services.course_agent_service import CourseAgentService
from app.tasks.rag_indexation import UPLOAD_DIR, index_course_resources

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/courses", tags=["Admin - Courses"])


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
    cats = course.taxonomy_categories or []
    return CourseResponse(
        id=str(course.id),
        slug=course.slug,
        title_fr=course.title_fr,
        title_en=course.title_en,
        description_fr=course.description_fr,
        description_en=course.description_en,
        course_domain=[tc.slug for tc in cats if tc.type == "domain"],
        course_level=[tc.slug for tc in cats if tc.type == "level"],
        audience_type=[tc.slug for tc in cats if tc.type == "audience"],
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

    # Look up taxonomy categories by slug
    all_slugs = (
        [(s, "domain") for s in request.course_domain]
        + [(s, "level") for s in request.course_level]
        + [(s, "audience") for s in request.audience_type]
    )
    tax_cats = []
    if all_slugs:
        result_cats = await db.execute(
            select(TaxonomyCategory).where(
                TaxonomyCategory.slug.in_([s for s, _ in all_slugs])
            )
        )
        tax_cats = list(result_cats.scalars().all())

    course = Course(
        id=uuid.uuid4(),
        slug=slug,
        title_fr=request.title_fr,
        title_en=request.title_en,
        description_fr=request.description_fr,
        description_en=request.description_en,
        languages=request.languages,
        estimated_hours=request.estimated_hours,
        cover_image_url=request.cover_image_url,
        rag_collection_id=request.rag_collection_id or str(uuid.uuid4()),
        created_by=uuid.UUID(current_user.id),
        status="draft",
        taxonomy_categories=tax_cats,
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

    taxonomy_fields = {"course_domain", "course_level", "audience_type"}
    for field, value in request.model_dump(exclude_unset=True).items():
        if field not in taxonomy_fields:
            setattr(course, field, value)

    # Update taxonomy if any taxonomy fields were provided
    data = request.model_dump(exclude_unset=True)
    if taxonomy_fields & data.keys():
        all_slugs = (
            [(s, "domain") for s in data.get("course_domain", [])]
            + [(s, "level") for s in data.get("course_level", [])]
            + [(s, "audience") for s in data.get("audience_type", [])]
        )
        if all_slugs:
            result_cats = await db.execute(
                select(TaxonomyCategory).where(
                    TaxonomyCategory.slug.in_([s for s, _ in all_slugs])
                )
            )
            course.taxonomy_categories = list(result_cats.scalars().all())
        else:
            course.taxonomy_categories = []

    await db.commit()
    await db.refresh(course)
    return _course_to_response(course)


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Publish a draft course. Admin only."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    # Check RAG indexation is complete before publishing
    chunk_count = await db.execute(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.source == course.rag_collection_id)
    )
    if chunk_count.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish: RAG indexation not complete. "
            "Upload resources and run indexation first.",
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

    # Clear existing modules — regenerate replaces, not appends
    await db.execute(delete(Module).where(Module.course_id == course_id))
    await db.flush()

    cats = course.taxonomy_categories or []
    agent = CourseAgentService()
    module_dicts = await agent.generate_course_structure(
        title_fr=course.title_fr,
        title_en=course.title_en,
        course_domain=[tc.slug for tc in cats if tc.type == "domain"],
        course_level=[tc.slug for tc in cats if tc.type == "level"],
        audience_type=[tc.slug for tc in cats if tc.type == "audience"],
        estimated_hours=request.estimated_hours or course.estimated_hours,
    )

    saved_modules = []
    for i, m in enumerate(module_dicts):
        module = Module(
            id=uuid.uuid4(),
            module_number=i + 1,
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
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    if not course.rag_collection_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course has no rag_collection_id",
        )

    task = index_course_resources.delay(str(course_id), course.rag_collection_id)
    logger.info(
        "RAG indexation triggered",
        course_id=str(course_id),
        task_id=task.id,
        admin_id=current_user.id,
    )
    return {"task_id": task.id, "status": "started"}


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

    # Count existing chunks for this course
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

    # If task_id provided, check Celery task status
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

ALLOWED_RESOURCE_TYPES = {"application/pdf"}
MAX_RESOURCE_SIZE = 100 * 1024 * 1024  # 100 MB


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
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only PDF files are accepted. Got: {content_type}",
        )

    data = await file.read()
    if len(data) > MAX_RESOURCE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds maximum size of 100MB",
        )

    if not data.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File does not appear to be a valid PDF",
        )

    safe_name = re.sub(r"[^\w.\-]", "_", Path(file.filename or "resource.pdf").name)
    if not safe_name.lower().endswith(".pdf"):
        safe_name += ".pdf"

    course_dir = UPLOAD_DIR / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    dest = course_dir / safe_name

    dest.write_bytes(data)

    logger.info(
        "Course resource uploaded",
        course_id=str(course_id),
        filename=safe_name,
        size_bytes=len(data),
        admin_id=current_user.id,
    )

    return {
        "course_id": str(course_id),
        "name": safe_name,
        "size_bytes": len(data),
    }


@router.delete("/{course_id}/resources/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course_resource(
    course_id: uuid.UUID,
    filename: str,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete an uploaded resource file from a course."""
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    safe_name = re.sub(r"[^\w.\-]", "_", Path(filename).name)
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
