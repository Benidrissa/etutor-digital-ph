"""Organization-scoped curriculum management endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.domain.models.course import Course
from app.domain.models.curriculum import Curriculum, CurriculumCourse
from app.domain.models.organization import OrgMemberRole
from app.domain.models.user_group import CurriculumAccess
from app.domain.services.organization_service import OrganizationService

router = APIRouter(
    prefix="/organizations/{org_id}/curricula",
    tags=["Organization Curricula"],
)

_org_svc = OrganizationService()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateCurriculumRequest(BaseModel):
    title_fr: str = Field(..., min_length=1)
    title_en: str = Field(..., min_length=1)
    slug: str
    description_fr: str | None = None
    description_en: str | None = None
    cover_image_url: str | None = None


class UpdateCurriculumRequest(BaseModel):
    title_fr: str | None = None
    title_en: str | None = None
    description_fr: str | None = None
    description_en: str | None = None
    cover_image_url: str | None = None


class SetCoursesRequest(BaseModel):
    course_ids: list[str]


class CurriculumResponse(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None = None
    description_en: str | None = None
    cover_image_url: str | None = None
    status: str
    organization_id: str | None = None
    course_count: int = 0


class CurriculumDetailResponse(CurriculumResponse):
    courses: list[dict]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _curriculum_response(c: Curriculum, course_count: int = 0) -> CurriculumResponse:
    return CurriculumResponse(
        id=str(c.id),
        slug=c.slug,
        title_fr=c.title_fr,
        title_en=c.title_en,
        description_fr=c.description_fr,
        description_en=c.description_en,
        cover_image_url=c.cover_image_url,
        status=c.status,
        organization_id=str(c.organization_id) if c.organization_id else None,
        course_count=course_count,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CurriculumResponse])
async def list_org_curricula(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[CurriculumResponse]:
    """List org-scoped curricula + platform curricula the org has access to."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))

    # Org-scoped curricula
    result = await db.execute(select(Curriculum).where(Curriculum.organization_id == org_id))
    org_curricula = result.scalars().all()

    # Platform curricula accessible via org's user group
    org = await _org_svc.get_organization(db, org_id)
    platform_curricula = []
    if org.user_group_id:
        access_result = await db.execute(
            select(Curriculum)
            .join(CurriculumAccess, CurriculumAccess.curriculum_id == Curriculum.id)
            .where(
                CurriculumAccess.group_id == org.user_group_id,
                Curriculum.organization_id.is_(None),
            )
        )
        platform_curricula = access_result.scalars().all()

    all_curricula = list(org_curricula) + list(platform_curricula)
    responses = []
    for c in all_curricula:
        count = await db.scalar(
            select(func.count(CurriculumCourse.course_id)).where(
                CurriculumCourse.curriculum_id == c.id
            )
        )
        responses.append(_curriculum_response(c, count or 0))
    return responses


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CurriculumResponse)
async def create_org_curriculum(
    org_id: uuid.UUID,
    body: CreateCurriculumRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurriculumResponse:
    """Create an org-scoped curriculum."""
    await _org_svc.require_org_role(
        db,
        org_id,
        uuid.UUID(current_user.id),
        OrgMemberRole.owner,
        OrgMemberRole.admin,
    )

    curriculum = Curriculum(
        slug=body.slug,
        title_fr=body.title_fr,
        title_en=body.title_en,
        description_fr=body.description_fr,
        description_en=body.description_en,
        cover_image_url=body.cover_image_url,
        organization_id=org_id,
        created_by=uuid.UUID(current_user.id),
        status="draft",
    )
    db.add(curriculum)
    await db.commit()
    await db.refresh(curriculum)
    return _curriculum_response(curriculum)


@router.get("/{curriculum_id}", response_model=CurriculumDetailResponse)
async def get_org_curriculum(
    org_id: uuid.UUID,
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurriculumDetailResponse:
    """Get curriculum detail with courses."""
    await _org_svc.require_org_role(db, org_id, uuid.UUID(current_user.id))

    curriculum = await db.get(Curriculum, curriculum_id)
    if not curriculum:
        raise HTTPException(status_code=404, detail="Curriculum not found.")

    # Get courses
    cc_result = await db.execute(
        select(Course)
        .join(CurriculumCourse, CurriculumCourse.course_id == Course.id)
        .where(CurriculumCourse.curriculum_id == curriculum_id)
    )
    courses = cc_result.scalars().all()

    return CurriculumDetailResponse(
        id=str(curriculum.id),
        slug=curriculum.slug,
        title_fr=curriculum.title_fr,
        title_en=curriculum.title_en,
        description_fr=curriculum.description_fr,
        description_en=curriculum.description_en,
        cover_image_url=curriculum.cover_image_url,
        status=curriculum.status,
        organization_id=str(curriculum.organization_id) if curriculum.organization_id else None,
        course_count=len(courses),
        courses=[
            {
                "id": str(c.id),
                "title_fr": c.title_fr,
                "title_en": c.title_en,
                "cover_image_url": c.cover_image_url,
            }
            for c in courses
        ],
    )


@router.patch("/{curriculum_id}", response_model=CurriculumResponse)
async def update_org_curriculum(
    org_id: uuid.UUID,
    curriculum_id: uuid.UUID,
    body: UpdateCurriculumRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurriculumResponse:
    """Update an org-scoped curriculum."""
    await _org_svc.require_org_role(
        db,
        org_id,
        uuid.UUID(current_user.id),
        OrgMemberRole.owner,
        OrgMemberRole.admin,
    )

    curriculum = await db.get(Curriculum, curriculum_id)
    if not curriculum or curriculum.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Curriculum not found.")

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(curriculum, key, value)

    await db.commit()
    await db.refresh(curriculum)
    return _curriculum_response(curriculum)


@router.put("/{curriculum_id}/courses", response_model=CurriculumResponse)
async def set_curriculum_courses(
    org_id: uuid.UUID,
    curriculum_id: uuid.UUID,
    body: SetCoursesRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurriculumResponse:
    """Set courses for an org curriculum (bulk replace)."""
    await _org_svc.require_org_role(
        db,
        org_id,
        uuid.UUID(current_user.id),
        OrgMemberRole.owner,
        OrgMemberRole.admin,
    )

    curriculum = await db.get(Curriculum, curriculum_id)
    if not curriculum or curriculum.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Curriculum not found.")

    # Delete existing
    existing = await db.execute(
        select(CurriculumCourse).where(CurriculumCourse.curriculum_id == curriculum_id)
    )
    for cc in existing.scalars().all():
        await db.delete(cc)

    # Add new
    for cid_str in body.course_ids:
        db.add(
            CurriculumCourse(
                curriculum_id=curriculum_id,
                course_id=uuid.UUID(cid_str),
            )
        )

    await db.commit()
    return _curriculum_response(curriculum, len(body.course_ids))


@router.post("/{curriculum_id}/publish", response_model=CurriculumResponse)
async def publish_org_curriculum(
    org_id: uuid.UUID,
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> CurriculumResponse:
    """Publish an org curriculum. Requires at least 1 course."""
    await _org_svc.require_org_role(
        db,
        org_id,
        uuid.UUID(current_user.id),
        OrgMemberRole.owner,
        OrgMemberRole.admin,
    )

    curriculum = await db.get(Curriculum, curriculum_id)
    if not curriculum or curriculum.organization_id != org_id:
        raise HTTPException(status_code=404, detail="Curriculum not found.")

    count = await db.scalar(
        select(func.count(CurriculumCourse.course_id)).where(
            CurriculumCourse.curriculum_id == curriculum_id
        )
    )
    if not count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot publish a curriculum with no courses.",
        )

    curriculum.status = "published"
    curriculum.published_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(curriculum)
    return _curriculum_response(curriculum, count)


@router.post(
    "/platform/{curriculum_id}/select",
    status_code=status.HTTP_201_CREATED,
)
async def select_platform_curriculum(
    org_id: uuid.UUID,
    curriculum_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Grant org access to an existing published platform curriculum."""
    await _org_svc.require_org_role(
        db,
        org_id,
        uuid.UUID(current_user.id),
        OrgMemberRole.owner,
        OrgMemberRole.admin,
    )

    org = await _org_svc.get_organization(db, org_id)
    if not org.user_group_id:
        raise HTTPException(status_code=400, detail="Organization has no user group.")

    curriculum = await db.get(Curriculum, curriculum_id)
    if not curriculum or curriculum.organization_id is not None:
        raise HTTPException(
            status_code=404,
            detail="Platform curriculum not found.",
        )

    # Check if already selected
    existing = await db.execute(
        select(CurriculumAccess).where(
            CurriculumAccess.curriculum_id == curriculum_id,
            CurriculumAccess.group_id == org.user_group_id,
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_selected"}

    db.add(
        CurriculumAccess(
            curriculum_id=curriculum_id,
            group_id=org.user_group_id,
            granted_by=uuid.UUID(current_user.id),
        )
    )
    await db.commit()
    return {"status": "selected"}
