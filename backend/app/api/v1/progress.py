"""Progress tracking API endpoints."""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.progress import (
    ErrorResponse,
    LessonAccessRequest,
    ModuleDetailWithProgressResponse,
    ModuleProgressResponse,
    UnitProgressDetail,
)
from app.domain.models.user import User
from app.domain.services.progress_service import ProgressService

logger = structlog.get_logger()
router = APIRouter(prefix="/progress", tags=["progress"])


def _make_module_progress_response(
    user_id: UUID, module_id: UUID, progress
) -> ModuleProgressResponse:
    return ModuleProgressResponse(
        module_id=module_id,
        user_id=user_id,
        status=progress.status,
        completion_pct=progress.completion_pct,
        quiz_score_avg=progress.quiz_score_avg,
        time_spent_minutes=progress.time_spent_minutes,
        last_accessed=(progress.last_accessed.isoformat() if progress.last_accessed else None),
    )


@router.post(
    "/lesson-access",
    response_model=ModuleProgressResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Module or lesson not found"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
)
async def track_lesson_access(
    request: LessonAccessRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleProgressResponse:
    """
    Record that the current user accessed a lesson.

    Marks the module as in_progress if it was locked.
    Creates a lesson_reading row for streak and time tracking.
    Returns updated module progress.
    """
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        progress = await service.track_lesson_access(
            user_id=user_id,
            module_id=request.module_id,
            lesson_id=request.lesson_id,
            time_spent_seconds=request.time_spent_seconds,
            reading_completion_pct=request.completion_percentage,
        )
        return _make_module_progress_response(user_id, request.module_id, progress)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Failed to track lesson access", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "tracking_failed", "message": "Failed to record lesson access"},
        )


@router.get(
    "/modules/{module_id}",
    response_model=ModuleProgressResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Module progress not found"},
    },
)
async def get_module_progress(
    module_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleProgressResponse:
    """Get current user's progress for a specific module."""
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        progress = await service.get_module_progress(user_id, module_id)

        if progress is None:
            return ModuleProgressResponse(
                module_id=module_id,
                user_id=user_id,
                status="locked",
                completion_pct=0.0,
                quiz_score_avg=None,
                time_spent_minutes=0,
                last_accessed=None,
            )

        return _make_module_progress_response(user_id, module_id, progress)

    except Exception as e:
        logger.error("Failed to get module progress", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "fetch_failed", "message": "Failed to retrieve module progress"},
        )


@router.get(
    "/modules",
    response_model=list[ModuleProgressResponse],
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def get_all_module_progress(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ModuleProgressResponse]:
    """Get current user's progress for all modules."""
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        all_progress = await service.get_all_module_progress(user_id)

        return [_make_module_progress_response(user_id, p.module_id, p) for p in all_progress]

    except Exception as e:
        logger.error("Failed to get all module progress", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "fetch_failed", "message": "Failed to retrieve progress"},
        )


@router.get(
    "/modules/{module_id}/detail",
    response_model=ModuleDetailWithProgressResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Module not found"},
    },
)
async def get_module_detail_with_progress(
    module_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleDetailWithProgressResponse:
    """
    Get full module detail including units with per-unit completion status.

    Used by the module overview page to show real progress instead of
    hardcoded static data.
    """
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        data = await service.get_module_with_progress(user_id, module_id)

        units = [UnitProgressDetail(**u) for u in data.pop("units", [])]
        return ModuleDetailWithProgressResponse(**data, units=units)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Failed to get module detail", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "fetch_failed", "message": "Failed to retrieve module detail"},
        )
