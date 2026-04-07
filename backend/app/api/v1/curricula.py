"""Public curriculum endpoints — list and detail for published curricula."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.domain.models.curriculum import Curriculum

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


@router.get("", response_model=list[CurriculumPublicResponse])
async def list_published_curricula(
    db=Depends(get_db_session),
) -> list[CurriculumPublicResponse]:
    """List all published curricula. No auth required."""
    result = await db.execute(
        select(Curriculum)
        .where(Curriculum.status == "published")
        .order_by(Curriculum.published_at.desc())
    )
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
    db=Depends(get_db_session),
) -> CurriculumPublicDetailResponse:
    """Get published curriculum detail with course IDs. No auth required."""
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
