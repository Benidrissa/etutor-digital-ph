"""Modules API endpoints — offline bundle for download."""

from __future__ import annotations

import re
import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_local_auth import get_current_user
from app.api.v1.schemas.modules import ErrorResponse, ModuleOfflineBundleResponse, UnitBundleSchema
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


async def _resolve_module_id(module_id: str, session: AsyncSession) -> UUID:
    """Resolve module code (M01) or UUID string to UUID."""
    try:
        return uuid.UUID(module_id)
    except ValueError:
        pass

    match = re.match(r"^M(\d{2})$", module_id.upper())
    if match:
        module_number = int(match.group(1))
        result = await session.execute(select(Module).where(Module.module_number == module_number))
        module = result.scalar_one_or_none()
        if module:
            return module.id
        raise ValueError(f"Module with code {module_id} not found")

    raise ValueError(
        f"Invalid module identifier: {module_id}. Expected UUID or module code (M01, M02, etc.)"
    )


@router.get(
    "/{module_id}/offline-bundle",
    response_model=ModuleOfflineBundleResponse,
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Module not found"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
    summary="Get offline bundle manifest for a module",
    description=(
        "Returns a structured manifest of all content for a module "
        "(lessons, quizzes, case studies, image URLs) so the frontend "
        "download manager can fetch and cache each item independently. "
        "Content items that are already in the generated_content table "
        "are referenced by ID so the client can fetch them without re-generation."
    ),
)
async def get_module_offline_bundle(
    module_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ModuleOfflineBundleResponse:
    """
    Return the offline bundle manifest for a module.

    The manifest lists all units with their cached content IDs.
    The frontend download manager iterates over units and fetches
    each content item (lesson / quiz / case study) individually.
    """
    try:
        resolved_id = await _resolve_module_id(module_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    result = await db.execute(select(Module).where(Module.id == resolved_id))
    module = result.scalar_one_or_none()
    if module is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Module {module_id} not found",
        )

    units_result = await db.execute(
        select(ModuleUnit)
        .where(ModuleUnit.module_id == resolved_id)
        .order_by(ModuleUnit.order_index)
    )
    units = units_result.scalars().all()

    content_result = await db.execute(
        select(GeneratedContent).where(GeneratedContent.module_id == resolved_id)
    )
    all_content = content_result.scalars().all()

    content_by_type: dict[str, list[GeneratedContent]] = {}
    for item in all_content:
        content_by_type.setdefault(item.content_type, []).append(item)

    unit_bundles: list[UnitBundleSchema] = []
    cached_count = 0

    for unit in units:
        lesson_id = None
        quiz_id = None
        case_id = None

        for lesson in content_by_type.get("lesson", []):
            if (
                lesson.content
                and isinstance(lesson.content, dict)
                and lesson.content.get("unit_id") == unit.unit_number
            ):
                lesson_id = str(lesson.id)
                cached_count += 1
                break

        for quiz in content_by_type.get("quiz", []):
            if (
                quiz.content
                and isinstance(quiz.content, dict)
                and quiz.content.get("unit_id") == unit.unit_number
            ):
                quiz_id = str(quiz.id)
                cached_count += 1
                break

        for case in content_by_type.get("case", []):
            if (
                case.content
                and isinstance(case.content, dict)
                and case.content.get("unit_id") == unit.unit_number
            ):
                case_id = str(case.id)
                cached_count += 1
                break

        unit_bundles.append(
            UnitBundleSchema(
                unit_id=str(unit.id),
                unit_number=unit.unit_number,
                title_fr=unit.title_fr,
                title_en=unit.title_en,
                description_fr=unit.description_fr,
                description_en=unit.description_en,
                estimated_minutes=unit.estimated_minutes,
                order_index=unit.order_index,
                lesson_content_id=lesson_id,
                quiz_content_id=quiz_id,
                case_study_content_id=case_id,
            )
        )

    unit_count = len(units)
    estimated_size = unit_count * (
        _BYTES_PER_LESSON
        + _BYTES_PER_QUIZ
        + _BYTES_PER_CASE_STUDY
        + _IMAGES_PER_UNIT * _BYTES_PER_IMAGE
    )

    logger.info(
        "offline_bundle_served",
        module_id=str(resolved_id),
        user_id=str(current_user.id),
        unit_count=unit_count,
        cached_count=cached_count,
    )

    return ModuleOfflineBundleResponse(
        module_id=str(resolved_id),
        module_number=module.module_number,
        title_fr=module.title_fr,
        title_en=module.title_en,
        description_fr=module.description_fr,
        description_en=module.description_en,
        estimated_hours=module.estimated_hours,
        level=module.level,
        units=unit_bundles,
        estimated_size_bytes=estimated_size,
        cached_content_count=cached_count,
    )
