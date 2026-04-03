"""Module API endpoints — offline bundle."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.modules import OfflineBundleResponse, OfflineBundleUnit
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/modules", tags=["modules"])

_BYTES_PER_LESSON = 15_000
_BYTES_PER_QUIZ = 8_000
_BYTES_PER_CASE_STUDY = 12_000
_BYTES_PER_IMAGE = 50_000
_IMAGES_PER_UNIT = 2


async def _resolve_module(module_id: str, session: AsyncSession) -> Module:
    """Resolve a module ID (UUID or M01 code) to a Module ORM instance."""
    try:
        uid = UUID(module_id)
        result = await session.execute(select(Module).where(Module.id == uid))
        module = result.scalar_one_or_none()
        if module:
            return module
    except ValueError:
        pass

    match = re.match(r"^M(\d{2})$", module_id.upper())
    if match:
        module_number = int(match.group(1))
        result = await session.execute(select(Module).where(Module.module_number == module_number))
        module = result.scalar_one_or_none()
        if module:
            return module

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"error": "module_not_found", "message": f"Module '{module_id}' not found"},
    )


@router.get(
    "/{module_id}/offline-bundle",
    response_model=OfflineBundleResponse,
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Module not found"},
        500: {"description": "Internal error"},
    },
)
async def get_offline_bundle(
    module_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OfflineBundleResponse:
    """
    Return structured manifest for offline module download.

    Includes all units with their cached content IDs and image URLs so
    the frontend download manager can fetch each piece independently.
    Size estimates are provided so the UI can show a pre-download summary.
    """
    try:
        module = await _resolve_module(module_id, db)

        units_result = await db.execute(
            select(ModuleUnit)
            .where(ModuleUnit.module_id == module.id)
            .order_by(ModuleUnit.order_index)
        )
        units = list(units_result.scalars().all())

        bundle_units: list[OfflineBundleUnit] = []
        total_bytes = 0

        for unit in units:
            lesson_result = await db.execute(
                select(GeneratedContent).where(
                    GeneratedContent.module_id == module.id,
                    GeneratedContent.content_type == "lesson",
                    GeneratedContent.content["unit_id"].astext == unit.unit_number,
                )
            )
            lesson = lesson_result.scalars().first()

            quiz_result = await db.execute(
                select(GeneratedContent).where(
                    GeneratedContent.module_id == module.id,
                    GeneratedContent.content_type == "quiz",
                    GeneratedContent.content["unit_id"].astext == unit.unit_number,
                )
            )
            quiz = quiz_result.scalars().first()

            case_study_result = await db.execute(
                select(GeneratedContent).where(
                    GeneratedContent.module_id == module.id,
                    GeneratedContent.content_type == "case",
                    GeneratedContent.content["unit_id"].astext == unit.unit_number,
                )
            )
            case_study = case_study_result.scalars().first()

            unit_size = (
                _BYTES_PER_LESSON
                + _BYTES_PER_QUIZ
                + _BYTES_PER_CASE_STUDY
                + _BYTES_PER_IMAGE * _IMAGES_PER_UNIT
            )
            total_bytes += unit_size

            bundle_units.append(
                OfflineBundleUnit(
                    unit_id=unit.unit_number,
                    unit_number=unit.unit_number,
                    order_index=unit.order_index,
                    title_fr=unit.title_fr,
                    title_en=unit.title_en,
                    estimated_minutes=unit.estimated_minutes,
                    size_bytes=unit_size,
                    content_ids={
                        "lesson": str(lesson.id) if lesson else None,
                        "quiz": str(quiz.id) if quiz else None,
                        "case_study": str(case_study.id) if case_study else None,
                    },
                    image_urls=[],
                )
            )

        logger.info(
            "offline_bundle_requested",
            module_id=str(module.id),
            user_id=str(current_user.id),
            units=len(bundle_units),
            total_bytes=total_bytes,
        )

        return OfflineBundleResponse(
            module_id=str(module.id),
            module_number=module.module_number,
            title_fr=module.title_fr,
            title_en=module.title_en,
            total_size_bytes=total_bytes,
            units=bundle_units,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("offline_bundle_failed", module_id=module_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "bundle_failed", "message": "Failed to build offline bundle"},
        )
