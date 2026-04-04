"""Expert endpoints for marketplace course management."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course, UserCourseEnrollment
from app.domain.models.module import Module
from app.domain.models.user import UserRole
from app.domain.services.course_agent_service import CourseAgentService
from app.tasks.rag_indexation import UPLOAD_DIR, index_course_resources

logger = get_logger(__name__)
router = APIRouter(prefix="/expert/courses", tags=["Expert - Courses"])

ALLOWED_RESOURCE_TYPES = {"application/pdf"}
MAX_RESOURCE_SIZE = 100 * 1024 * 1024  # 100 MB


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


class UpdateCourseRequest(BaseModel):
    title_fr: str | None = None
    title_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
    course_domain: list[str] | None = None
    course_level: list[str] | None = None
    audience_type: list[str] | None = None
    languages: str | None = None
    estimated_hours: int | None = None
    cover_image_url: str | None = None


class SetPriceRequest(BaseModel):
    credit_price: int = Field(..., ge=1, description="Price in credits (minimum 1)")


class GenerateStructureRequest(BaseModel):
    estimated_hours: int = 20


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
    expert_id: str | None
    rag_collection_id: str | None
    is_marketplace: bool
    credit_price: int | None
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
        expert_id=str(course.created_by) if course.created_by else None,
        rag_collection_id=course.rag_collection_id,
        is_marketplace=course.is_marketplace,
        credit_price=course.credit_price,
        created_at=course.created_at.isoformat(),
        published_at=course.published_at.isoformat() if course.published_at else None,
    )


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug


async def _get_own_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser,
    db,
) -> Course:
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if str(course.created_by) != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage this course",
        )
    return course


@router.get("", response_model=list[CourseResponse])
async def list_expert_courses(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> list[CourseResponse]:
    """List all courses created by the authenticated expert (all statuses)."""
    result = await db.execute(
        select(Course)
        .where(Course.created_by == uuid.UUID(current_user.id))
        .order_by(Course.created_at.desc())
    )
    courses = result.scalars().all()
    return [_course_to_response(c) for c in courses]


@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_expert_course(
    request: CreateCourseRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Create a new marketplace course draft. Sets is_marketplace=True."""
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
        course_domain=request.course_domain,
        course_level=request.course_level,
        audience_type=request.audience_type,
        languages=request.languages,
        estimated_hours=request.estimated_hours,
        cover_image_url=request.cover_image_url,
        rag_collection_id=str(uuid.uuid4()),
        created_by=uuid.UUID(current_user.id),
        status="draft",
        is_marketplace=True,
    )
    db.add(course)
    await db.commit()
    await db.refresh(course)

    logger.info(
        "Expert course created",
        course_id=str(course.id),
        expert_id=current_user.id,
    )
    return _course_to_response(course)


@router.get("/{course_id}", response_model=CourseResponse)
async def get_expert_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Get detail of an expert's own course."""
    course = await _get_own_course(course_id, current_user, db)
    return _course_to_response(course)


@router.patch("/{course_id}", response_model=CourseResponse)
async def update_expert_course(
    course_id: uuid.UUID,
    request: UpdateCourseRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Update metadata of an expert's own draft course."""
    course = await _get_own_course(course_id, current_user, db)

    if course.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft courses can be updated",
        )

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(course, field, value)

    await db.commit()
    await db.refresh(course)
    return _course_to_response(course)


@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expert_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> None:
    """Delete a draft course with no enrollments."""
    course = await _get_own_course(course_id, current_user, db)

    if course.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only draft courses can be deleted",
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
    logger.info("Expert course deleted", course_id=str(course_id), expert_id=current_user.id)


@router.post("/{course_id}/generate-structure")
async def generate_course_structure(
    course_id: uuid.UUID,
    request: GenerateStructureRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> dict:
    """AI-generate module structure for an expert's course. Deducts credits via CostTracker."""
    course = await _get_own_course(course_id, current_user, db)

    max_number_result = await db.execute(
        select(func.max(Module.module_number)).where(Module.course_id == course_id)
    )
    max_number = max_number_result.scalar_one() or 0

    agent = CourseAgentService()
    module_dicts = await agent.generate_course_structure(
        title_fr=course.title_fr,
        title_en=course.title_en,
        course_domain=list(course.course_domain or []),
        course_level=list(course.course_level or []),
        audience_type=list(course.audience_type or []),
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
        "Expert course structure generated",
        course_id=str(course_id),
        module_count=len(saved_modules),
        expert_id=current_user.id,
    )
    return {"modules": saved_modules, "count": len(saved_modules)}


@router.post("/{course_id}/set-price", response_model=CourseResponse)
async def set_course_price(
    course_id: uuid.UUID,
    request: SetPriceRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Set or update the credit price for an expert's marketplace course."""
    course = await _get_own_course(course_id, current_user, db)

    course.credit_price = request.credit_price
    await db.commit()
    await db.refresh(course)
    logger.info(
        "Expert course price set",
        course_id=str(course_id),
        credit_price=request.credit_price,
        expert_id=current_user.id,
    )
    return _course_to_response(course)


@router.post("/{course_id}/publish", response_model=CourseResponse)
async def publish_expert_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Publish a marketplace course. Requires at least 1 module and a price set."""
    course = await _get_own_course(course_id, current_user, db)

    if course.status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course is already published",
        )

    module_count_result = await db.execute(
        select(func.count()).select_from(Module).where(Module.course_id == course_id)
    )
    if module_count_result.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish: course must have at least 1 module",
        )

    if not course.credit_price:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish: credit price must be set first",
        )

    course.status = "published"
    course.published_at = datetime.now(UTC)
    course.module_count = module_count_result.scalar_one()

    await db.commit()
    await db.refresh(course)
    logger.info("Expert course published", course_id=str(course_id), expert_id=current_user.id)
    return _course_to_response(course)


@router.post("/{course_id}/unpublish", response_model=CourseResponse)
async def unpublish_expert_course(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> CourseResponse:
    """Revert a published marketplace course to draft."""
    course = await _get_own_course(course_id, current_user, db)

    if course.status != "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only published courses can be unpublished",
        )

    course.status = "draft"
    await db.commit()
    await db.refresh(course)
    logger.info("Expert course unpublished", course_id=str(course_id), expert_id=current_user.id)
    return _course_to_response(course)


@router.post("/{course_id}/resources", status_code=status.HTTP_201_CREATED)
async def upload_expert_course_resource(
    course_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> dict:
    """Upload a PDF resource for an expert's course."""
    await _get_own_course(course_id, current_user, db)

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
        "Expert course resource uploaded",
        course_id=str(course_id),
        filename=safe_name,
        size_bytes=len(data),
        expert_id=current_user.id,
    )
    return {
        "course_id": str(course_id),
        "name": safe_name,
        "size_bytes": len(data),
    }


@router.post("/{course_id}/index-resources")
async def trigger_expert_rag_indexation(
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.expert)),
    db=Depends(get_db_session),
) -> dict:
    """Trigger RAG indexation for expert course resources. Deducts embedding credits."""
    course = await _get_own_course(course_id, current_user, db)

    if not course.rag_collection_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course has no rag_collection_id",
        )

    task = index_course_resources.delay(str(course_id), course.rag_collection_id)
    logger.info(
        "Expert RAG indexation triggered",
        course_id=str(course_id),
        task_id=task.id,
        expert_id=current_user.id,
    )
    return {"task_id": task.id, "status": "started"}
