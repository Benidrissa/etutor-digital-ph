"""Admin endpoints for taxonomy category management (CRUD)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.taxonomy import CourseTaxonomy, TaxonomyCategory
from app.domain.models.user import UserRole

logger = get_logger(__name__)
router = APIRouter(prefix="/admin/taxonomy", tags=["Admin - Taxonomy"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TaxonomyCategoryCreate(BaseModel):
    type: str  # 'domain' | 'level' | 'audience'
    slug: str
    label_fr: str
    label_en: str
    sort_order: int = 0


class TaxonomyCategoryUpdate(BaseModel):
    label_fr: str | None = None
    label_en: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class TaxonomyCategoryResponse(BaseModel):
    id: str
    type: str
    slug: str
    label_fr: str
    label_en: str
    sort_order: int
    is_active: bool


def _to_response(cat: TaxonomyCategory) -> TaxonomyCategoryResponse:
    return TaxonomyCategoryResponse(
        id=str(cat.id),
        type=cat.type,
        slug=cat.slug,
        label_fr=cat.label_fr,
        label_en=cat.label_en,
        sort_order=cat.sort_order,
        is_active=cat.is_active,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

VALID_TYPES = {"domain", "level", "audience"}


@router.get("", response_model=dict)
async def list_taxonomy(
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> dict:
    """List all taxonomy categories grouped by type. Admin only."""
    result = await db.execute(
        select(TaxonomyCategory).order_by(TaxonomyCategory.type, TaxonomyCategory.sort_order)
    )
    categories = result.scalars().all()

    grouped: dict[str, list] = {"domains": [], "levels": [], "audience_types": []}
    type_key_map = {
        "domain": "domains",
        "level": "levels",
        "audience": "audience_types",
    }

    for cat in categories:
        key = type_key_map.get(cat.type)
        if key:
            grouped[key].append(_to_response(cat).model_dump())

    return grouped


@router.post("", response_model=TaxonomyCategoryResponse, status_code=201)
async def create_taxonomy_category(
    request: TaxonomyCategoryCreate,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> TaxonomyCategoryResponse:
    """Create a new taxonomy category. Admin only."""
    if request.type not in VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid type. Must be one of: {', '.join(VALID_TYPES)}",
        )

    # Check for duplicate slug within type
    existing = await db.execute(
        select(TaxonomyCategory).where(
            TaxonomyCategory.type == request.type,
            TaxonomyCategory.slug == request.slug,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Slug '{request.slug}' already exists for type '{request.type}'",
        )

    cat = TaxonomyCategory(
        id=uuid.uuid4(),
        type=request.type,
        slug=request.slug,
        label_fr=request.label_fr,
        label_en=request.label_en,
        sort_order=request.sort_order,
    )
    db.add(cat)
    await db.commit()
    await db.refresh(cat)

    logger.info(
        "Taxonomy category created",
        category_id=str(cat.id),
        type=cat.type,
        slug=cat.slug,
        admin_id=current_user.id,
    )
    return _to_response(cat)


@router.patch("/{category_id}", response_model=TaxonomyCategoryResponse)
async def update_taxonomy_category(
    category_id: uuid.UUID,
    request: TaxonomyCategoryUpdate,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> TaxonomyCategoryResponse:
    """Update a taxonomy category. Admin only."""
    result = await db.execute(select(TaxonomyCategory).where(TaxonomyCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    for field, value in request.model_dump(exclude_unset=True).items():
        setattr(cat, field, value)

    await db.commit()
    await db.refresh(cat)

    logger.info(
        "Taxonomy category updated",
        category_id=str(cat.id),
        admin_id=current_user.id,
    )
    return _to_response(cat)


@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_taxonomy_category(
    category_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db=Depends(get_db_session),
) -> None:
    """Delete a taxonomy category. Fails if referenced by courses. Admin only."""
    result = await db.execute(select(TaxonomyCategory).where(TaxonomyCategory.id == category_id))
    cat = result.scalar_one_or_none()
    if not cat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )

    # Check if any courses reference this category
    usage = await db.execute(
        select(CourseTaxonomy).where(CourseTaxonomy.category_id == category_id)
    )
    if usage.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete: this category is used by one or more courses.",
        )

    await db.delete(cat)
    await db.commit()

    logger.info(
        "Taxonomy category deleted",
        category_id=str(category_id),
        type=cat.type,
        slug=cat.slug,
        admin_id=current_user.id,
    )
