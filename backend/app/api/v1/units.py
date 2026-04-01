"""Module units API endpoints."""

from __future__ import annotations

import re
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.units import (
    ModuleUnitResponse,
    ModuleUnitsResponse,
    UnitCreateRequest,
    UnitUpdateRequest,
)
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit

logger = structlog.get_logger()
router = APIRouter(prefix="/modules", tags=["units"])


async def _resolve_module(module_id: str, session: AsyncSession) -> Module:
    """Resolve module by UUID or code (M01..M15). Raises 404 if not found."""
    try:
        mid = uuid.UUID(module_id)
        query = select(Module).where(Module.id == mid)
    except ValueError:
        m = re.match(r"^M(\d{2})$", module_id.upper())
        if not m:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_module_id", "message": f"Invalid module identifier: {module_id}"},
            )
        query = select(Module).where(Module.module_number == int(m.group(1)))

    result = await session.execute(query)
    module = result.scalar_one_or_none()
    if not module:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "module_not_found", "message": f"Module {module_id} not found"},
        )
    return module


@router.get(
    "/{module_id}/units",
    response_model=ModuleUnitsResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid module identifier"},
        404: {"description": "Module not found"},
    },
)
async def get_module_units(
    module_id: str,
    session: AsyncSession = Depends(get_db),
) -> ModuleUnitsResponse:
    """
    List all units for a given module.

    Accepts both module codes (e.g., M01) and UUIDs.
    Returns units ordered by order_index.
    """
    module = await _resolve_module(module_id, session)

    query = (
        select(ModuleUnit)
        .where(ModuleUnit.module_id == module.id)
        .order_by(ModuleUnit.order_index)
    )
    result = await session.execute(query)
    units = result.scalars().all()

    logger.info("Module units retrieved", module_id=str(module.id), count=len(units))

    unit_responses = [ModuleUnitResponse.model_validate(u) for u in units]
    return ModuleUnitsResponse(
        module_id=module.id,
        units=unit_responses,
        total=len(unit_responses),
    )


@router.post(
    "/{module_id}/units",
    response_model=ModuleUnitResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Invalid request or module identifier"},
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "Module not found"},
        409: {"description": "Unit number already exists"},
    },
)
async def create_module_unit(
    module_id: str,
    body: UnitCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ModuleUnitResponse:
    """Create a new unit for a module (admin only)."""
    if getattr(current_user, "professional_role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Admin role required"},
        )

    module = await _resolve_module(module_id, session)

    existing = await session.execute(
        select(ModuleUnit).where(
            ModuleUnit.module_id == module.id,
            ModuleUnit.unit_number == body.unit_number,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "unit_exists", "message": f"Unit {body.unit_number} already exists in module"},
        )

    new_unit = ModuleUnit(
        module_id=module.id,
        unit_number=body.unit_number,
        title_fr=body.title_fr,
        title_en=body.title_en,
        description_fr=body.description_fr,
        description_en=body.description_en,
        estimated_minutes=body.estimated_minutes,
        order_index=body.order_index,
        unit_type=body.unit_type,
        books_sources=body.books_sources,
    )
    session.add(new_unit)
    await session.commit()
    await session.refresh(new_unit)

    logger.info(
        "Module unit created",
        unit_id=str(new_unit.id),
        module_id=str(module.id),
        unit_number=body.unit_number,
    )
    return ModuleUnitResponse.model_validate(new_unit)


@router.patch(
    "/{module_id}/units/{unit_id}",
    response_model=ModuleUnitResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid request"},
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "Module or unit not found"},
    },
)
async def update_module_unit(
    module_id: str,
    unit_id: uuid.UUID,
    body: UnitUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ModuleUnitResponse:
    """Update an existing unit (admin only). Changing title invalidates cached generated_content."""
    if getattr(current_user, "professional_role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Admin role required"},
        )

    module = await _resolve_module(module_id, session)

    result = await session.execute(
        select(ModuleUnit).where(ModuleUnit.id == unit_id, ModuleUnit.module_id == module.id)
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unit_not_found", "message": f"Unit {unit_id} not found in module {module_id}"},
        )

    title_changed = False
    if body.title_fr is not None and body.title_fr != unit.title_fr:
        unit.title_fr = body.title_fr
        title_changed = True
    if body.title_en is not None and body.title_en != unit.title_en:
        unit.title_en = body.title_en
        title_changed = True
    if body.description_fr is not None:
        unit.description_fr = body.description_fr
    if body.description_en is not None:
        unit.description_en = body.description_en
    if body.estimated_minutes is not None:
        unit.estimated_minutes = body.estimated_minutes
    if body.order_index is not None:
        unit.order_index = body.order_index
    if body.unit_type is not None:
        unit.unit_type = body.unit_type
    if body.books_sources is not None:
        unit.books_sources = body.books_sources

    if title_changed:
        from app.domain.models.content import GeneratedContent
        from sqlalchemy import delete

        await session.execute(
            delete(GeneratedContent).where(
                GeneratedContent.module_id == module.id,
                GeneratedContent.content.op("->>")("unit_id") == unit.unit_number,
            )
        )
        logger.info(
            "Cached generated content invalidated for unit",
            unit_id=str(unit.id),
            unit_number=unit.unit_number,
        )

    await session.commit()
    await session.refresh(unit)

    logger.info("Module unit updated", unit_id=str(unit.id), title_changed=title_changed)
    return ModuleUnitResponse.model_validate(unit)


@router.delete(
    "/{module_id}/units/{unit_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Admin role required"},
        404: {"description": "Module or unit not found"},
    },
)
async def delete_module_unit(
    module_id: str,
    unit_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Delete a unit (admin only)."""
    if getattr(current_user, "professional_role", None) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "message": "Admin role required"},
        )

    module = await _resolve_module(module_id, session)

    result = await session.execute(
        select(ModuleUnit).where(ModuleUnit.id == unit_id, ModuleUnit.module_id == module.id)
    )
    unit = result.scalar_one_or_none()
    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "unit_not_found", "message": f"Unit {unit_id} not found in module {module_id}"},
        )

    await session.delete(unit)
    await session.commit()

    logger.info("Module unit deleted", unit_id=str(unit_id), module_id=str(module.id))
