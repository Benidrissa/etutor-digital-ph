"""Source image API endpoints — serve WebP binaries and metadata from reference PDFs."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.api.deps_local_auth import AuthenticatedUser, get_current_user, require_role
from app.api.v1.schemas.source_images import (
    SourceImageListResponse,
    SourceImageMetadataResponse,
)
from app.domain.models.source_image import SourceImage
from app.domain.models.user import UserRole
from app.infrastructure.storage.s3 import S3StorageService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/source-images", tags=["Source Images"])

_CACHE_IMMUTABLE = "public, max-age=31536000, immutable"


@router.get(
    "/{image_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"image/webp": {}}, "description": "WebP binary image data"},
        302: {"description": "Redirect to storage URL when binary is not proxied"},
        404: {"description": "Image not found"},
    },
)
async def get_source_image_data(
    image_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """Serve the WebP binary for a source image extracted from a reference PDF.

    - Returns binary `image/webp` with long-lived cache headers when the image
      is stored in S3/MinIO and can be proxied.
    - Falls back to a 302 redirect to the public storage URL when direct proxy
      is not configured.
    - Returns 404 if the image is not found or has no storage reference.
    """
    result = await db.execute(select(SourceImage).where(SourceImage.id == image_id))
    img = result.scalar_one_or_none()

    if img is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "source_image_not_found", "message": f"Image {image_id} not found"},
        )

    if img.storage_url:
        logger.info("Redirecting to source image storage URL", image_id=str(image_id))
        return Response(
            status_code=status.HTTP_302_FOUND,
            headers={
                "Location": img.storage_url,
                "Cache-Control": _CACHE_IMMUTABLE,
            },
        )

    if img.storage_key:
        try:
            storage = S3StorageService()
            public_url = storage.public_url(img.storage_key)
            logger.info("Redirecting to MinIO public URL", image_id=str(image_id))
            return Response(
                status_code=status.HTTP_302_FOUND,
                headers={
                    "Location": public_url,
                    "Cache-Control": _CACHE_IMMUTABLE,
                },
            )
        except Exception as exc:
            logger.warning(
                "Failed to build MinIO URL, returning 404",
                image_id=str(image_id),
                error=str(exc),
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "source_image_data_unavailable",
            "message": f"Image {image_id} has no storage reference",
        },
    )


@router.get(
    "/by-source/{source}",
    response_model=SourceImageListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_source_images_by_source(
    source: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    _current_user: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db_session),
) -> SourceImageListResponse:
    """List all source images for a book or collection (admin only, paginated).

    The `source` parameter can be a named book identifier (e.g. ``donaldson``,
    ``triola``, ``scutchfield``) or a RAG collection UUID string.
    """
    offset = (page - 1) * limit

    count_result = await db.execute(select(func.count()).where(SourceImage.source == source))
    total: int = count_result.scalar_one()

    rows_result = await db.execute(
        select(SourceImage)
        .where(SourceImage.source == source)
        .order_by(SourceImage.page_number, SourceImage.created_at)
        .offset(offset)
        .limit(limit)
    )
    images = rows_result.scalars().all()

    logger.info(
        "Source images listed",
        source=source,
        page=page,
        limit=limit,
        total=total,
    )

    return SourceImageListResponse(
        items=[SourceImageMetadataResponse.model_validate(img) for img in images],
        total=total,
        page=page,
        limit=limit,
        has_next=(offset + limit) < total,
    )


@router.get(
    "/{image_id}",
    response_model=SourceImageMetadataResponse,
    status_code=status.HTTP_200_OK,
)
async def get_source_image_metadata(
    image_id: uuid.UUID,
    _current_user: AuthenticatedUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> SourceImageMetadataResponse:
    """Return metadata for a single source image (no binary data)."""
    result = await db.execute(select(SourceImage).where(SourceImage.id == image_id))
    img = result.scalar_one_or_none()

    if img is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "source_image_not_found", "message": f"Image {image_id} not found"},
        )

    logger.info("Source image metadata fetched", image_id=str(image_id))
    return SourceImageMetadataResponse.model_validate(img)
