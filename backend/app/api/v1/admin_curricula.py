"""Admin endpoints for curriculum management (CRUD, publish, archive, course assignment)."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.course import Course
from app.domain.models.curriculum import Curriculum, CurriculumCourse
from app.domain.models.user import User, UserRole
from app.domain.models.user_group import CurriculumAccess, UserGroup

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/curricula", tags=["Admin - Curricula"])


class CreateCurriculumRequest(BaseModel):
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    cover_image_url: str | None = None


class UpdateCurriculumRequest(BaseModel):
    title_fr: str | None = None
    title_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
    cover_image_url: str | None = None


class SetVisibilityRequest(BaseModel):
    visibility: str


class GrantAccessRequest(BaseModel):
    user_id: str | None = None
    group_id: str | None = None


class AccessEntryResponse(BaseModel):
    id: str
    curriculum_id: str
    user_id: str | None
    user_email: str | None
    group_id: str | None
    group_name: str | None
    granted_by: str | None
    granted_at: str


class CurriculumResponse(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    cover_image_url: str | None
    status: str
    visibility: str
    created_by: str | None
    course_count: int
    created_at: str
    published_at: str | None


class CurriculumDetailResponse(CurriculumResponse):
    courses: list[dict]


class AssignCoursesRequest(BaseModel):
    course_ids: list[str]


def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    slug = re.sub(r"^-+|-+$", "", slug)
    return slug


def _curriculum_to_response(curriculum: Curriculum) -> CurriculumResponse:
    return CurriculumResponse(
        id=str(curriculum.id),
        slug=curriculum.slug,
        title_fr=curriculum.title_fr,
        title_en=curriculum.title_en,
        description_fr=curriculum.description_fr,
        description_en=curriculum.description_en,
        cover_image_url=curriculum.cover_image_url,
        status=curriculum.status,
        visibility=curriculum.visibility,
        created_by=str(curriculum.created_by) if curriculum.created_by else None,
        course_count=len(curriculum.courses) if curriculum.courses else 0,
        created_at=curriculum.created_at.isoformat(),
        published_at=curriculum.published_at.isoformat() if curriculum.published_at else None,
    )


def _curriculum_to_detail_response(curriculum: Curriculum) -> CurriculumDetailResponse:
    base = _curriculum_to_response(curriculum)
    courses_data = []
    for course in curriculum.courses or []:
        courses_data.append(
            {
                "id": str(course.id),
                "slug": course.slug,
                "title_fr": course.title_fr,
                "title_en": course.title_en,
                "status": course.status,
                "module_count": course.module_count,
                "estimated_hours": course.estimated_hours,
            }
        )
    return CurriculumDetailResponse(**base.model_dump(), courses=courses_data)


@router.get("", response_model=list[CurriculumResponse])
async def list_curricula_admin(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> list[CurriculumResponse]:
    """List all curricula (any status). Admin only."""
    result = await db.execute(select(Curriculum).order_by(Curriculum.created_at.desc()))
    curricula = result.scalars().all()
    return [_curriculum_to_response(c) for c in curricula]


@router.post("", response_model=CurriculumDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_curriculum(
    request: CreateCurriculumRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Create a new curriculum (draft). Admin only."""
    base_slug = _slugify(request.title_en or request.title_fr)
    slug = base_slug
    suffix = 1
    while True:
        existing = await db.execute(select(Curriculum).where(Curriculum.slug == slug))
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    curriculum = Curriculum(
        id=uuid.uuid4(),
        slug=slug,
        title_fr=request.title_fr,
        title_en=request.title_en,
        description_fr=request.description_fr,
        description_en=request.description_en,
        cover_image_url=request.cover_image_url,
        created_by=uuid.UUID(current_user.id),
        status="draft",
    )
    db.add(curriculum)
    await db.commit()
    await db.refresh(curriculum)

    logger.info("Curriculum created", curriculum_id=str(curriculum.id), admin_id=current_user.id)
    return _curriculum_to_detail_response(curriculum)


@router.get("/{curriculum_id}", response_model=CurriculumDetailResponse)
async def get_curriculum_admin(
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Get curriculum detail with courses. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")
    return _curriculum_to_detail_response(curriculum)


@router.patch("/{curriculum_id}", response_model=CurriculumDetailResponse)
async def update_curriculum(
    curriculum_id: uuid.UUID,
    request: UpdateCurriculumRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Update curriculum metadata. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(curriculum, field, value)

    await db.commit()
    await db.refresh(curriculum)
    logger.info("Curriculum updated", curriculum_id=str(curriculum_id), admin_id=current_user.id)
    return _curriculum_to_detail_response(curriculum)


@router.post("/{curriculum_id}/publish", response_model=CurriculumDetailResponse)
async def publish_curriculum(
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Publish a draft curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")
    if curriculum.status == "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Curriculum is already published"
        )

    curriculum.status = "published"
    curriculum.published_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(curriculum)
    logger.info("Curriculum published", curriculum_id=str(curriculum_id), admin_id=current_user.id)
    return _curriculum_to_detail_response(curriculum)


@router.post("/{curriculum_id}/archive", response_model=CurriculumDetailResponse)
async def archive_curriculum(
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Archive a curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    curriculum.status = "archived"
    await db.commit()
    await db.refresh(curriculum)
    logger.info("Curriculum archived", curriculum_id=str(curriculum_id), admin_id=current_user.id)
    return _curriculum_to_detail_response(curriculum)


@router.delete("/{curriculum_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_curriculum(
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete a curriculum. Admin only. Cannot delete published curricula."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")
    if curriculum.status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Archive the curriculum before deleting",
        )

    await db.delete(curriculum)
    await db.commit()
    logger.info("Curriculum deleted", curriculum_id=str(curriculum_id), admin_id=current_user.id)


@router.put("/{curriculum_id}/courses", response_model=CurriculumDetailResponse)
async def assign_courses(
    curriculum_id: uuid.UUID,
    request: AssignCoursesRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Replace courses assigned to a curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    course_uuids = []
    for cid in request.course_ids:
        try:
            course_uuids.append(uuid.UUID(cid))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid course_id: {cid}"
            )

    if course_uuids:
        courses_result = await db.execute(select(Course).where(Course.id.in_(course_uuids)))
        found_courses = courses_result.scalars().all()
        if len(found_courses) != len(course_uuids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more courses not found",
            )
        curriculum.courses = list(found_courses)
    else:
        curriculum.courses = []

    await db.commit()
    await db.refresh(curriculum)
    logger.info(
        "Curriculum courses updated",
        curriculum_id=str(curriculum_id),
        course_count=len(request.course_ids),
        admin_id=current_user.id,
    )
    return _curriculum_to_detail_response(curriculum)


@router.post("/{curriculum_id}/courses/{course_id}", response_model=CurriculumDetailResponse)
async def add_course_to_curriculum(
    curriculum_id: uuid.UUID,
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Add a single course to a curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    course_result = await db.execute(select(Course).where(Course.id == course_id))
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")

    existing = await db.execute(
        select(CurriculumCourse).where(
            CurriculumCourse.curriculum_id == curriculum_id,
            CurriculumCourse.course_id == course_id,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(CurriculumCourse(curriculum_id=curriculum_id, course_id=course_id))
        await db.commit()

    await db.refresh(curriculum)
    return _curriculum_to_detail_response(curriculum)


@router.delete(
    "/{curriculum_id}/courses/{course_id}",
    response_model=CurriculumDetailResponse,
)
async def remove_course_from_curriculum(
    curriculum_id: uuid.UUID,
    course_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Remove a single course from a curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    junction = await db.execute(
        select(CurriculumCourse).where(
            CurriculumCourse.curriculum_id == curriculum_id,
            CurriculumCourse.course_id == course_id,
        )
    )
    junction_row = junction.scalar_one_or_none()
    if junction_row:
        await db.delete(junction_row)
        await db.commit()

    await db.refresh(curriculum)
    return _curriculum_to_detail_response(curriculum)


@router.post("/{curriculum_id}/visibility", response_model=CurriculumDetailResponse)
async def set_curriculum_visibility(
    curriculum_id: uuid.UUID,
    request: SetVisibilityRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Set curriculum visibility to 'public' or 'private'. Admin only."""
    if request.visibility not in ("public", "private"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visibility must be 'public' or 'private'",
        )
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    curriculum = result.scalar_one_or_none()
    if not curriculum:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    curriculum.visibility = request.visibility
    await db.commit()
    await db.refresh(curriculum)
    logger.info(
        "Curriculum visibility updated",
        curriculum_id=str(curriculum_id),
        visibility=request.visibility,
        admin_id=current_user.id,
    )
    return _curriculum_to_detail_response(curriculum)


@router.get("/{curriculum_id}/access", response_model=list[AccessEntryResponse])
async def list_curriculum_access(
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> list[AccessEntryResponse]:
    """List all access entries for a curriculum. Admin only."""
    result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    access_result = await db.execute(
        select(CurriculumAccess).where(CurriculumAccess.curriculum_id == curriculum_id)
    )
    entries = access_result.scalars().all()

    response = []
    for entry in entries:
        user_email = None
        group_name = None
        if entry.user_id:
            user_result = await db.execute(select(User).where(User.id == entry.user_id))
            user = user_result.scalar_one_or_none()
            user_email = user.email if user else None
        if entry.group_id:
            group_result = await db.execute(select(UserGroup).where(UserGroup.id == entry.group_id))
            group = group_result.scalar_one_or_none()
            group_name = group.name if group else None

        response.append(
            AccessEntryResponse(
                id=str(entry.id),
                curriculum_id=str(entry.curriculum_id),
                user_id=str(entry.user_id) if entry.user_id else None,
                user_email=user_email,
                group_id=str(entry.group_id) if entry.group_id else None,
                group_name=group_name,
                granted_by=str(entry.granted_by) if entry.granted_by else None,
                granted_at=entry.granted_at.isoformat(),
            )
        )
    return response


@router.post(
    "/{curriculum_id}/access",
    response_model=AccessEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def grant_curriculum_access(
    curriculum_id: uuid.UUID,
    request: GrantAccessRequest,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> AccessEntryResponse:
    """Grant access to a private curriculum for a user or group. Admin only."""
    if not request.user_id and not request.group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either user_id or group_id must be provided",
        )
    if request.user_id and request.group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only one of user_id or group_id can be provided",
        )

    curriculum_result = await db.execute(select(Curriculum).where(Curriculum.id == curriculum_id))
    if not curriculum_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Curriculum not found")

    user_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    user_email = None
    group_name = None

    if request.user_id:
        try:
            user_id = uuid.UUID(request.user_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user_id")
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        user_email = user.email

        existing = await db.execute(
            select(CurriculumAccess).where(
                CurriculumAccess.curriculum_id == curriculum_id,
                CurriculumAccess.user_id == user_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User already has access to this curriculum",
            )

    if request.group_id:
        try:
            group_id = uuid.UUID(request.group_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid group_id")
        group_result = await db.execute(select(UserGroup).where(UserGroup.id == group_id))
        group = group_result.scalar_one_or_none()
        if not group:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
        group_name = group.name

        existing = await db.execute(
            select(CurriculumAccess).where(
                CurriculumAccess.curriculum_id == curriculum_id,
                CurriculumAccess.group_id == group_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Group already has access to this curriculum",
            )

    entry = CurriculumAccess(
        id=uuid.uuid4(),
        curriculum_id=curriculum_id,
        user_id=user_id,
        group_id=group_id,
        granted_by=uuid.UUID(current_user.id),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info(
        "Curriculum access granted",
        curriculum_id=str(curriculum_id),
        user_id=str(user_id) if user_id else None,
        group_id=str(group_id) if group_id else None,
        admin_id=current_user.id,
    )
    return AccessEntryResponse(
        id=str(entry.id),
        curriculum_id=str(entry.curriculum_id),
        user_id=str(entry.user_id) if entry.user_id else None,
        user_email=user_email,
        group_id=str(entry.group_id) if entry.group_id else None,
        group_name=group_name,
        granted_by=str(entry.granted_by) if entry.granted_by else None,
        granted_at=entry.granted_at.isoformat(),
    )


@router.delete("/{curriculum_id}/access/{access_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_curriculum_access(
    curriculum_id: uuid.UUID,
    access_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> None:
    """Revoke access to a private curriculum. Admin only."""
    result = await db.execute(
        select(CurriculumAccess).where(
            CurriculumAccess.id == access_id,
            CurriculumAccess.curriculum_id == curriculum_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Access entry not found")

    await db.delete(entry)
    await db.commit()
    logger.info(
        "Curriculum access revoked",
        curriculum_id=str(curriculum_id),
        access_id=str(access_id),
        admin_id=current_user.id,
    )
