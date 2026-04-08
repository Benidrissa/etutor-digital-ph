"""Public curriculum endpoints — list and detail for published curricula."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import exists, select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_optional_user
from app.domain.models.curriculum import Curriculum
from app.domain.models.user_group import CurriculumAccess, UserGroupMember

logger = get_logger(__name__)
router = APIRouter(prefix="/curricula", tags=["Curricula"])


class CurriculumPublicResponse(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    cover_image_url: str | None
    course_count: int
    published_at: str | None


class CurriculumPublicDetailResponse(CurriculumPublicResponse):
    course_ids: list[str]


def _user_has_access(curriculum_id: uuid.UUID, user_id: uuid.UUID):
    """Subquery: returns True if user has direct or group-based access."""
    direct = exists(
        select(CurriculumAccess.id).where(
            CurriculumAccess.curriculum_id == curriculum_id,
            CurriculumAccess.user_id == user_id,
        )
    )
    via_group = exists(
        select(CurriculumAccess.id)
        .join(
            UserGroupMember,
            UserGroupMember.group_id == CurriculumAccess.group_id,
        )
        .where(
            CurriculumAccess.curriculum_id == curriculum_id,
            UserGroupMember.user_id == user_id,
        )
    )
    return direct | via_group


@router.get("", response_model=list[CurriculumPublicResponse])
async def list_published_curricula(
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> list[CurriculumPublicResponse]:
    """List published curricula. Private curricula only shown if user has access."""
    stmt = (
        select(Curriculum)
        .where(Curriculum.status == "published")
        .order_by(Curriculum.published_at.desc())
    )

    if current_user:
        uid = uuid.UUID(current_user.id)
        direct_access = exists(
            select(CurriculumAccess.id).where(
                CurriculumAccess.curriculum_id == Curriculum.id,
                CurriculumAccess.user_id == uid,
            )
        )
        group_access = exists(
            select(CurriculumAccess.id)
            .join(UserGroupMember, UserGroupMember.group_id == CurriculumAccess.group_id)
            .where(
                CurriculumAccess.curriculum_id == Curriculum.id,
                UserGroupMember.user_id == uid,
            )
        )
        stmt = stmt.where((Curriculum.visibility == "public") | direct_access | group_access)
    else:
        stmt = stmt.where(Curriculum.visibility == "public")

    result = await db.execute(stmt)
    curricula = result.scalars().all()

    return [
        CurriculumPublicResponse(
            id=str(c.id),
            slug=c.slug,
            title_fr=c.title_fr,
            title_en=c.title_en,
            description_fr=c.description_fr,
            description_en=c.description_en,
            cover_image_url=c.cover_image_url,
            course_count=len(c.courses) if c.courses else 0,
            published_at=c.published_at.isoformat() if c.published_at else None,
        )
        for c in curricula
    ]


@router.get("/{slug_or_id}", response_model=CurriculumPublicDetailResponse)
async def get_curriculum_detail(
    slug_or_id: str,
    current_user=Depends(get_optional_user),
    db=Depends(get_db_session),
) -> CurriculumPublicDetailResponse:
    """Get published curriculum detail. Private curricula require access."""
    curriculum: Curriculum | None = None

    try:
        cid = uuid.UUID(slug_or_id)
        result = await db.execute(
            select(Curriculum).where(Curriculum.id == cid, Curriculum.status == "published")
        )
        curriculum = result.scalar_one_or_none()
    except ValueError:
        pass

    if not curriculum:
        result = await db.execute(
            select(Curriculum).where(
                Curriculum.slug == slug_or_id, Curriculum.status == "published"
            )
        )
        curriculum = result.scalar_one_or_none()

    if not curriculum:
        raise HTTPException(status_code=404, detail="Curriculum not found")

    if curriculum.visibility == "private":
        if not current_user:
            raise HTTPException(status_code=404, detail="Curriculum not found")
        uid = uuid.UUID(current_user.id)
        direct = await db.execute(
            select(CurriculumAccess).where(
                CurriculumAccess.curriculum_id == curriculum.id,
                CurriculumAccess.user_id == uid,
            )
        )
        has_access = direct.scalar_one_or_none() is not None
        if not has_access:
            group_q = await db.execute(
                select(CurriculumAccess)
                .join(UserGroupMember, UserGroupMember.group_id == CurriculumAccess.group_id)
                .where(
                    CurriculumAccess.curriculum_id == curriculum.id,
                    UserGroupMember.user_id == uid,
                )
            )
            has_access = group_q.scalar_one_or_none() is not None
        if not has_access:
            raise HTTPException(status_code=404, detail="Curriculum not found")

    return CurriculumPublicDetailResponse(
        id=str(curriculum.id),
        slug=curriculum.slug,
        title_fr=curriculum.title_fr,
        title_en=curriculum.title_en,
        description_fr=curriculum.description_fr,
        description_en=curriculum.description_en,
        cover_image_url=curriculum.cover_image_url,
        course_count=len(curriculum.courses) if curriculum.courses else 0,
        published_at=curriculum.published_at.isoformat() if curriculum.published_at else None,
        course_ids=[str(course.id) for course in (curriculum.courses or [])],
    )
