"""Progress tracking API endpoints."""

from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.content import _resolve_module_id
from app.api.v1.schemas.progress import (
    CompleteLessonRequest,
    CompleteLessonResponse,
    ErrorResponse,
    LessonAccessRequest,
    ModuleDetailWithProgressResponse,
    ModuleProgressResponse,
    UnitProgressDetail,
)
from app.domain.models.user import User
from app.domain.services.platform_settings_service import SettingsCache
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
    module_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleProgressResponse:
    """Get current user's progress for a specific module."""
    try:
        resolved_id = await _resolve_module_id(module_id, db)
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        progress = await service.get_module_progress(user_id, resolved_id)

        if progress is None:
            return ModuleProgressResponse(
                module_id=resolved_id,
                user_id=user_id,
                status="not_started",
                completion_pct=0.0,
                quiz_score_avg=None,
                time_spent_minutes=0,
                last_accessed=None,
            )

        return _make_module_progress_response(user_id, resolved_id, progress)

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
    course_id: Annotated[UUID | None, Query(description="Filter modules by course ID")] = None,
) -> list[ModuleProgressResponse]:
    """
    Get current user's progress for all modules.

    When course_id is provided, only modules belonging to that course are returned.
    Without course_id, returns ALL modules, ordered by module_number.
    Modules with no progress record have status 'not_started' and 0% completion;
    they remain accessible to enrolled learners (no sequential gating).
    """
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        all_modules = await service.get_all_modules_with_progress(user_id, course_id=course_id)

        return [
            ModuleProgressResponse(
                module_id=m["module_id"],
                user_id=m["user_id"],
                module_number=m["module_number"],
                title_fr=m["title_fr"],
                title_en=m["title_en"],
                description_fr=m["description_fr"],
                description_en=m["description_en"],
                level=m["level"],
                estimated_hours=m["estimated_hours"],
                status=m["status"],
                completion_pct=m["completion_pct"],
                quiz_score_avg=m["quiz_score_avg"],
                time_spent_minutes=m["time_spent_minutes"],
                last_accessed=m["last_accessed"],
            )
            for m in all_modules
        ]

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
    module_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleDetailWithProgressResponse:
    """
    Get full module detail including units with per-unit completion status.

    Used by the module overview page to show real progress instead of
    hardcoded static data.
    """
    try:
        resolved_id = await _resolve_module_id(module_id, db)
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)
        data = await service.get_module_with_progress(user_id, resolved_id)

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


@router.post(
    "/complete-lesson",
    response_model=CompleteLessonResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Quiz not passed"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
)
async def complete_lesson(
    request: CompleteLessonRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CompleteLessonResponse:
    """
    Mark a unit/lesson as completed.

    Requires a passing quiz attempt (score ≥ 80%) for the given module + unit.
    Returns 403 with error code 'quiz_required' if no passing attempt exists.
    """
    try:
        user_id = UUID(str(current_user.id))
        service = ProgressService(db)

        quiz_passed = await service.check_quiz_passed_for_unit(
            user_id=user_id,
            module_id=request.module_id,
            unit_id=request.unit_id,
        )

        if not quiz_passed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "quiz_required",
                    "message": "Pass the unit quiz with ≥80% to complete this lesson",
                },
            )

        progress = await service.update_progress_after_quiz(
            user_id=user_id,
            module_id=request.module_id,
            unit_id=request.unit_id,
            score=SettingsCache.instance().get("progress-unit-pass-score", 80.0),
            passed=True,
        )

        logger.info(
            "Lesson completed via complete-lesson endpoint",
            user_id=str(user_id),
            module_id=str(request.module_id),
            unit_id=request.unit_id,
            completion_pct=progress.completion_pct,
        )

        return CompleteLessonResponse(
            completed=True,
            module_progress=_make_module_progress_response(user_id, request.module_id, progress),
        )

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.error("Failed to complete lesson", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "completion_failed", "message": "Failed to complete lesson"},
        )
