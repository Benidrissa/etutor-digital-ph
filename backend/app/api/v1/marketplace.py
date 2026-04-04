"""Marketplace API endpoints — browse, purchase, review."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import get_current_user, get_optional_user
from app.domain.services.marketplace_service import MarketplaceService

logger = get_logger(__name__)
router = APIRouter(prefix="/marketplace", tags=["Marketplace"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MarketplaceCourseItem(BaseModel):
    id: str
    slug: str
    title_fr: str
    title_en: str
    description_fr: str | None
    description_en: str | None
    course_domain: list[str]
    course_level: list[str]
    audience_type: list[str]
    estimated_hours: int
    module_count: int
    cover_image_url: str | None
    languages: str
    price_credits: int
    avg_rating: float
    review_count: int
    enrollment_count: int
    expert_name: str | None
    expert_avatar: str | None
    is_enrolled: bool = False


class MarketplaceCourseDetail(MarketplaceCourseItem):
    modules_preview: list[dict]
    enrollment_status: str | None = None


class BrowseResponse(BaseModel):
    total: int
    items: list[MarketplaceCourseItem]


class PurchaseResponse(BaseModel):
    course_id: str
    user_id: str
    status: str
    enrolled_at: str
    credits_spent: int


class ReviewRequest(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = None


class ReviewResponse(BaseModel):
    id: str
    listing_id: str
    user_id: str
    rating: int
    comment: str | None
    created_at: str


class ReviewItem(BaseModel):
    id: str
    rating: int
    comment: str | None
    created_at: str
    reviewer_name: str | None
    reviewer_avatar: str | None


class ReviewListResponse(BaseModel):
    total: int
    items: list[ReviewItem]


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_marketplace_service(
    db: AsyncSession = Depends(get_db_session),
) -> MarketplaceService:
    return MarketplaceService(db)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/courses", response_model=BrowseResponse)
async def browse_marketplace_courses(
    course_domain: str | None = Query(None),
    course_level: str | None = Query(None),
    audience_type: str | None = Query(None),
    search: str | None = Query(None),
    price_min: int | None = Query(None, ge=0),
    price_max: int | None = Query(None, ge=0),
    sort: str = Query(
        "newest",
        pattern="^(newest|popular|highest_rated|price_asc|price_desc)$",
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_optional_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> BrowseResponse:
    """Browse published marketplace courses. Auth optional."""
    result = await service.browse_courses(
        course_domain=course_domain,
        course_level=course_level,
        audience_type=audience_type,
        search=search,
        price_min=price_min,
        price_max=price_max,
        sort=sort,
        limit=limit,
        offset=offset,
        current_user_id=current_user.id if current_user else None,
    )
    return BrowseResponse(**result)


@router.get("/courses/{slug}", response_model=MarketplaceCourseDetail)
async def get_marketplace_course(
    slug: str,
    current_user=Depends(get_optional_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> MarketplaceCourseDetail:
    """Get marketplace course detail by slug. Auth optional."""
    detail = await service.get_course_detail(
        slug=slug,
        current_user_id=current_user.id if current_user else None,
    )
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found in marketplace",
        )
    return MarketplaceCourseDetail(**detail)


@router.post("/courses/{course_id}/purchase", response_model=PurchaseResponse)
async def purchase_course(
    course_id: uuid.UUID,
    current_user=Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> PurchaseResponse:
    """Purchase a marketplace course with credits and auto-enroll. Auth required."""
    try:
        result = await service.purchase_course(
            course_id=course_id,
            user_id=current_user.id,
        )
    except ValueError as exc:
        error = str(exc)
        if error == "course_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found in marketplace",
            )
        if error == "already_enrolled":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Already enrolled in this course",
            )
        if error == "insufficient_credits":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Insufficient credits",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Purchase failed",
        )

    logger.info(
        "Course purchased",
        user_id=current_user.id,
        course_id=str(course_id),
    )
    return PurchaseResponse(**result)


@router.post(
    "/courses/{course_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_review(
    course_id: uuid.UUID,
    body: ReviewRequest,
    current_user=Depends(get_current_user),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> ReviewResponse:
    """Leave a review for a marketplace course. Must be enrolled. Auth required."""
    try:
        result = await service.create_review(
            course_id=course_id,
            user_id=current_user.id,
            rating=body.rating,
            comment=body.comment,
        )
    except ValueError as exc:
        error = str(exc)
        if error == "listing_not_found":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Course not found in marketplace",
            )
        if error == "not_enrolled":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You must be enrolled to review this course",
            )
        if error == "review_exists":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already reviewed this course",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to create review",
        )

    return ReviewResponse(**result)


@router.get("/courses/{course_id}/reviews", response_model=ReviewListResponse)
async def list_reviews(
    course_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: MarketplaceService = Depends(get_marketplace_service),
) -> ReviewListResponse:
    """List reviews for a marketplace course. Public."""
    result = await service.list_reviews(
        course_id=course_id,
        limit=limit,
        offset=offset,
    )
    return ReviewListResponse(**result)
