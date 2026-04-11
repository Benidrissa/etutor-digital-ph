"""Source image API endpoints — serve metadata and binary data from RAG-indexed PDFs."""

import uuid

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.api.v1.schemas.source_images import SourceImageListResponse, SourceImageMetadataResponse
from app.domain.models.source_image import SourceImage
from app.domain.models.user import UserRole

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/source-images", tags=["Source Images"])


@router.get(
    "/by-source/{source}",
    response_model=SourceImageListResponse,
)
async def list_images_by_source(
    source: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    _current_user: AuthenticatedUser = Depends(require_role(UserRole.admin, UserRole.sub_admin)),
    db: AsyncSession = Depends(get_db),
) -> SourceImageListResponse:
    """List all source images for a given book/collection (admin only, paginated)."""
    offset = (page - 1) * limit

    count_result = await db.execute(select(SourceImage).where(SourceImage.source == source))
    all_items = count_result.scalars().all()
    total = len(all_items)

    result = await db.execute(
        select(SourceImage)
        .where(SourceImage.source == source)
        .order_by(SourceImage.page_number)
        .offset(offset)
        .limit(limit)
    )
    images = result.scalars().all()

    return SourceImageListResponse(
        items=[SourceImageMetadataResponse.model_validate(img) for img in images],
        total=total,
    )


@router.get(
    "/{image_id}",
    response_model=SourceImageMetadataResponse,
)
async def get_image_metadata(
    image_id: uuid.UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SourceImageMetadataResponse:
    """Return metadata JSON for a source image (auth required)."""
    result = await db.execute(select(SourceImage).where(SourceImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    return SourceImageMetadataResponse.model_validate(img)


@router.get("/{image_id}/data")
async def get_image_data(
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Proxy image binary from internal MinIO storage to the browser."""
    result = await db.execute(select(SourceImage).where(SourceImage.id == image_id))
    img = result.scalar_one_or_none()
    if img is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    if not img.storage_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Image binary not available"
        )

    logger.info("Source image data proxy", image_id=str(image_id))
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.get(img.storage_url)
        upstream.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch image from storage", image_id=str(image_id), error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Image not available from storage"
        ) from exc

    content_type = upstream.headers.get("content-type", "image/webp")
    return StreamingResponse(
        content=iter([upstream.content]),
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
