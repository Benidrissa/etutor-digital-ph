"""Serve story-mode art images (#2675): ``GET /api/v1/story-art/{id}/data``.

The story routes attach an ``art`` map whose URLs point here. Like the lesson
illustrations' data route (``/images/{id}/data``) it needs no token, so a plain
``<img src>`` works, and a ready image is cached as immutable: a redrawn image
is stored under a new id, so an id never names two different images.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.domain.models.story_art import STATUS_READY, StoryArt

router = APIRouter(prefix="/story-art", tags=["Story art"])

IMMUTABLE = "public, max-age=31536000, immutable"


@router.get(
    "/{art_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"image/webp": {}}, "description": "The image (WebP)"},
        404: {"description": "Unknown image (story_art_not_found), or not ready"},
    },
)
async def get_story_art_data(
    art_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """The WebP of one character pose or backdrop, cached as immutable when ready."""
    row = (
        await db.execute(select(StoryArt.status, StoryArt.image_data).where(StoryArt.id == art_id))
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "story_art_not_found", "message": f"No story art {art_id}"},
        )
    art_status, image_data = row
    if art_status != STATUS_READY or not image_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "story_art_not_ready",
                "message": f"Story art {art_id} is not ready (status: {art_status})",
            },
        )
    return Response(
        content=image_data,
        media_type="image/webp",
        headers={"Cache-Control": IMMUTABLE},
    )
