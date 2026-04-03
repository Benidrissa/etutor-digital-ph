"""Admin endpoints for platform settings management."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from structlog import get_logger

from app.api.deps import get_db as get_db_session
from app.api.deps_local_auth import (
    AuthenticatedUser,
    require_role,
)
from app.domain.models.audit_log import AdminAction, AuditLog
from app.domain.models.user import UserRole
from app.domain.services.platform_settings_service import (
    PlatformSettingsService,
)
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


# ── Public endpoint (no auth) ─────────────────────────────────


@router.get(
    "/settings/public",
    response_model=PublicSettingsResponse,
)
async def get_public_settings():
    """Return non-sensitive settings for the frontend."""
    data = await _svc.get_all_public()
    return PublicSettingsResponse(settings=data)


# ── Admin endpoints ────────────────────────────────────────────


@router.get(
    "/admin/settings",
    response_model=list[SettingsByCategoryResponse],
)
async def list_settings(
    admin: AuthenticatedUser = Depends(
        require_role(UserRole.admin)
    ),
):
    """List all settings grouped by category."""
    result = []
    for cat in CATEGORIES:
        items = await _svc.get_by_category(cat)
        result.append(
            SettingsByCategoryResponse(
                category=cat,
                settings=[SettingResponse(**s) for s in items],
            )
        )
    return result


@router.get(
    "/admin/settings/{key:path}",
    response_model=SettingResponse,
)
async def get_setting(
    key: str,
    admin: AuthenticatedUser = Depends(
        require_role(UserRole.admin)
    ),
):
    """Get a single setting by key."""
    all_settings = await _svc.get_all()
    for s in all_settings:
        if s["key"] == key:
            return SettingResponse(**s)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Setting '{key}' not found",
    )


@router.patch(
    "/admin/settings/{key:path}",
    response_model=SettingResponse,
)
async def update_setting(
    key: str,
    body: SettingUpdateRequest,
    admin: AuthenticatedUser = Depends(
        require_role(UserRole.admin)
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """Update a setting's value."""
    # Get old value for audit log
    old_value = await _svc.get(key)

    try:
        updated = await _svc.set(key, body.value)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting '{key}' not found",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # Audit log
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            admin_id=uuid.UUID(admin.id),
            admin_email=admin.email,
            action=AdminAction.update_setting,
            details=json.dumps({
                "key": key,
                "old_value": old_value,
                "new_value": body.value,
            }),
        )
    )
    await db.commit()

    return SettingResponse(**updated)


@router.post(
    "/admin/settings/{key:path}/reset",
    response_model=SettingResponse,
)
async def reset_setting(
    key: str,
    admin: AuthenticatedUser = Depends(
        require_role(UserRole.admin)
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """Reset a setting to its default value."""
    old_value = await _svc.get(key)

    try:
        reset = await _svc.reset_to_default(key)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Setting '{key}' not found",
        )

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            admin_id=uuid.UUID(admin.id),
            admin_email=admin.email,
            action=AdminAction.reset_setting,
            details=json.dumps({
                "key": key,
                "old_value": old_value,
            }),
        )
    )
    await db.commit()

    return SettingResponse(**reset)


@router.post(
    "/admin/settings/reset-category/{category}",
    response_model=ResetCategoryResponse,
)
async def reset_category(
    category: str,
    admin: AuthenticatedUser = Depends(
        require_role(UserRole.admin)
    ),
    db: AsyncSession = Depends(get_db_session),
):
    """Reset all settings in a category to defaults."""
    if category not in CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category '{category}' not found",
        )

    count = await _svc.reset_category(category)

    if count:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                admin_id=uuid.UUID(admin.id),
                admin_email=admin.email,
                action=AdminAction.reset_category,
                details=json.dumps({
                    "category": category,
                    "reset_count": count,
                }),
            )
        )
        await db.commit()

    return ResetCategoryResponse(
        category=category,
        reset_count=count,
    )
