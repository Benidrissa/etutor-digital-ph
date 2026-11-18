"""Serve the story prop library's pictures: ``GET /api/v1/story-props/{id}/data``.

The story routes attach ``art.props`` whose URLs point here (Phase A of
docs/story-mode-3d-assets.md). Like the story-art route it needs no token, so
a plain ``<img src>`` works, and a picture is cached as immutable: a changed
picture is imported under a new id, so an id never names two pictures.
``?size=large`` serves a close-up's 960 px version.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.domain.models.story_prop_library import StoryLibraryAsset

router = APIRouter(prefix="/story-props", tags=["Story props"])

IMMUTABLE = "public, max-age=31536000, immutable"


@router.get(
    "/{asset_id}/data",
    status_code=status.HTTP_200_OK,
    responses={
        200: {"content": {"image/webp": {}}, "description": "The picture (WebP)"},
        404: {"description": "Unknown picture (story_prop_not_found), or no large version"},
    },
)
async def get_story_prop_data(
    asset_id: UUID,
    size: Literal["small", "large"] = Query("small"),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    """The WebP of one library sticker or close-up, cached as immutable."""
    column = StoryLibraryAsset.image_large if size == "large" else StoryLibraryAsset.image_data
    row = (await db.execute(select(column).where(StoryLibraryAsset.id == asset_id))).first()
    if row is None or not row[0]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "story_prop_not_found",
                "message": f"No story prop picture {asset_id} ({size})",
            },
        )
    return Response(content=row[0], media_type="image/webp", headers={"Cache-Control": IMMUTABLE})
