"""Admin endpoints for platform settings management."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import AuthenticatedUser, require_role
from app.domain.models.audit_log import AdminAction, AuditLog
from app.domain.models.user import UserRole
from app.domain.services.platform_settings_service import PlatformSettingsService
from app.infrastructure.config.platform_defaults import CATEGORIES

from .schemas.settings import (
    PublicSettingsResponse,
    ResetCategoryResponse,
    SettingResponse,
    SettingsByCategoryResponse,
    SettingUpdateRequest,
)

logger = get_logger(__name__)
router = APIRouter(tags=["Settings"])
_svc = PlatformSettingsService()


@router.get("/settings/public", response_model=PublicSettingsResponse)
async def get_public_settings():
    return PublicSettingsResponse(settings=await _svc.get_all_public())


@router.get("/admin/settings", response_model=list[SettingsByCategoryResponse])
async def list_settings(
    admin: AuthenticatedUser = Depends(require_role(UserRole.admin)),
):
    return [
        SettingsByCategoryResponse(
            category=cat,
            settings=[SettingResponse(**s) for s in await _svc.get_by_category(cat)],
        )
        for cat in CATEGORIES
    ]


@router.get("/admin/settings/{key:path}", response_model=SettingResponse)
async def get_setting(
    key: str,
    admin: AuthenticatedUser = Depends(require_role(UserRole.admin)),
):
    for s in await _svc.get_all():
        if s["key"] == key:
            return SettingResponse(**s)
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"Setting '{key}' not found")


@router.patch("/admin/settings/{key:path}", response_model=SettingResponse)
async def update_setting(
    key: str,
    body: SettingUpdateRequest,
    admin: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db_session),
):
    old_value = await _svc.get(key)
    try:
        updated = await _svc.set(key, body.value)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Setting '{key}' not found")
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    db.add(AuditLog(
        id=uuid.uuid4(), admin_id=uuid.UUID(admin.id), admin_email=admin.email,
        action=AdminAction.update_setting,
        details=json.dumps({"key": key, "old_value": old_value, "new_value": body.value}),
    ))
    await db.commit()
    return SettingResponse(**updated)


@router.post("/admin/settings/{key:path}/reset", response_model=SettingResponse)
async def reset_setting(
    key: str,
    admin: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db_session),
):
    old_value = await _svc.get(key)
    try:
        reset = await _svc.reset_to_default(key)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Setting '{key}' not found")
    db.add(AuditLog(
        id=uuid.uuid4(), admin_id=uuid.UUID(admin.id), admin_email=admin.email,
        action=AdminAction.reset_setting,
        details=json.dumps({"key": key, "old_value": old_value}),
    ))
    await db.commit()
    return SettingResponse(**reset)


@router.post("/admin/settings/reset-category/{category}", response_model=ResetCategoryResponse)
async def reset_category(
    category: str,
    admin: AuthenticatedUser = Depends(require_role(UserRole.admin)),
    db: AsyncSession = Depends(get_db_session),
):
    if category not in CATEGORIES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Category '{category}' not found")
    count = await _svc.reset_category(category)
    if count:
        db.add(AuditLog(
            id=uuid.uuid4(), admin_id=uuid.UUID(admin.id), admin_email=admin.email,
            action=AdminAction.reset_category,
            details=json.dumps({"category": category, "reset_count": count}),
        ))
        await db.commit()
    return ResetCategoryResponse(category=category, reset_count=count)
