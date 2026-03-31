"""Modules API endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.modules import ModuleListResponse, ModuleUnlockStatusResponse
from app.domain.models.user import User
from app.domain.services.module_service import ModuleService

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("", response_model=ModuleListResponse)
async def list_modules(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleListResponse:
    """
    Get all 15 modules with user progress and unlock status.

    Returns module information including:
    - Basic module details (title, description, level)
    - User progress (completion %, quiz scores, time spent)
    - Lock/unlock status based on prerequisite completion

    **Module unlock rule:** Module unlocks when ALL prerequisite modules achieve:
    - ≥80% completion percentage AND
    - ≥80% average quiz score

    M01 (Foundations) is always unlocked.
    """
    try:
        service = ModuleService(db)
        modules = await service.get_modules_with_progress(current_user.id)

        return ModuleListResponse(modules=modules)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve modules: {str(e)}")


@router.get("/{module_id}/unlock-status", response_model=ModuleUnlockStatusResponse)
async def get_module_unlock_status(
    module_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleUnlockStatusResponse:
    """
    Get detailed unlock status for a specific module.

    Returns:
    - Current unlock status
    - Detailed prerequisite requirements and progress
    - What's needed to unlock the module
    """
    try:
        service = ModuleService(db)
        status = await service.get_module_unlock_status(current_user.id, module_id)

        return ModuleUnlockStatusResponse(**status)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get unlock status: {str(e)}")


@router.post("/{module_id}/unlock")
async def unlock_module(
    module_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, str]:
    """
    Attempt to unlock a module if prerequisites are met.

    This endpoint checks if the user has met all prerequisite requirements
    and unlocks the module if eligible. Typically called when:
    - User completes a quiz with ≥80% score
    - User reaches 80% completion on a module
    - Manual unlock check is requested
    """
    try:
        service = ModuleService(db)
        was_unlocked = await service.unlock_module_if_eligible(current_user.id, module_id)

        if was_unlocked:
            return {"message": "Module unlocked successfully"}
        else:
            return {"message": "Module unlock requirements not met"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to unlock module: {str(e)}")
