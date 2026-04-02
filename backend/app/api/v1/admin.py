"""Admin endpoints for managing tutor rate limits."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps_local_auth import AuthenticatedUser, get_current_user
from app.api.v1.schemas.admin import (
    GlobalRateLimitResponse,
    ResetUserUsageResponse,
    SetUserRateLimitRequest,
    UpdateGlobalRateLimitRequest,
    UsageListResponse,
    UserRateLimitOverrideResponse,
    UserUsageResponse,
)
from app.domain.services.rate_limit_config_service import RateLimitConfigService
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def get_rate_limit_config_service() -> RateLimitConfigService:
    return RateLimitConfigService()


async def require_admin(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Dependency that raises 403 if the caller is not an admin."""
    settings = get_settings()
    admin_emails = [e.strip() for e in settings.admin_emails.split(",") if e.strip()]
    if current_user.email not in admin_emails and not getattr(current_user, "is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


@router.get(
    "/rate-limits/global",
    response_model=GlobalRateLimitResponse,
    summary="Get global tutor rate limit",
)
async def get_global_rate_limit(
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> GlobalRateLimitResponse:
    """Return the current global daily tutor message limit."""
    limit = await service.get_global_limit()
    return GlobalRateLimitResponse(daily_limit=limit)


@router.put(
    "/rate-limits/global",
    response_model=GlobalRateLimitResponse,
    summary="Update global tutor rate limit",
)
async def update_global_rate_limit(
    request: UpdateGlobalRateLimitRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> GlobalRateLimitResponse:
    """Update the global daily tutor message limit."""
    await service.set_global_limit(request.daily_limit)
    logger.info(
        "Admin updated global rate limit",
        admin_email=_admin.email,
        new_limit=request.daily_limit,
    )
    return GlobalRateLimitResponse(daily_limit=request.daily_limit)


@router.get(
    "/rate-limits/users",
    response_model=UsageListResponse,
    summary="List all users with today's usage",
)
async def list_user_usages(
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> UsageListResponse:
    """Return today's usage and effective limit for every active user."""
    users_data = await service.get_all_active_users_usage()
    global_limit = await service.get_global_limit()
    users = [
        UserUsageResponse(
            user_id=u["user_id"],
            usage_today=u["usage_today"],
            effective_limit=u["effective_limit"],
            override_limit=u["override_limit"],
        )
        for u in users_data
    ]
    return UsageListResponse(users=users, global_limit=global_limit)


@router.get(
    "/rate-limits/users/{user_id}",
    response_model=UserRateLimitOverrideResponse,
    summary="Get rate limit info for a specific user",
)
async def get_user_rate_limit(
    user_id: str,
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> UserRateLimitOverrideResponse:
    """Return override limit, usage today and effective limit for a user."""
    override = await service.get_user_override(user_id)
    usage = await service.get_user_usage_today(user_id)
    effective = await service.get_effective_limit(user_id)
    return UserRateLimitOverrideResponse(
        user_id=user_id,
        override_limit=override,
        usage_today=usage,
        effective_limit=effective,
    )


@router.put(
    "/rate-limits/users/{user_id}",
    response_model=UserRateLimitOverrideResponse,
    summary="Set per-user rate limit override",
)
async def set_user_rate_limit(
    user_id: str,
    request: SetUserRateLimitRequest,
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> UserRateLimitOverrideResponse:
    """Set a per-user daily tutor message limit override."""
    await service.set_user_override(user_id, request.daily_limit)
    usage = await service.get_user_usage_today(user_id)
    logger.info(
        "Admin set per-user rate limit",
        admin_email=_admin.email,
        user_id=user_id,
        limit=request.daily_limit,
    )
    return UserRateLimitOverrideResponse(
        user_id=user_id,
        override_limit=request.daily_limit,
        usage_today=usage,
        effective_limit=request.daily_limit,
    )


@router.delete(
    "/rate-limits/users/{user_id}/override",
    response_model=UserRateLimitOverrideResponse,
    summary="Remove per-user rate limit override",
)
async def delete_user_rate_limit_override(
    user_id: str,
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> UserRateLimitOverrideResponse:
    """Remove a per-user override so the user falls back to the global limit."""
    await service.delete_user_override(user_id)
    usage = await service.get_user_usage_today(user_id)
    effective = await service.get_effective_limit(user_id)
    logger.info(
        "Admin removed per-user rate limit override",
        admin_email=_admin.email,
        user_id=user_id,
    )
    return UserRateLimitOverrideResponse(
        user_id=user_id,
        override_limit=None,
        usage_today=usage,
        effective_limit=effective,
    )


@router.post(
    "/rate-limits/users/{user_id}/reset",
    response_model=ResetUserUsageResponse,
    summary="Reset a user's daily usage counter",
)
async def reset_user_usage(
    user_id: str,
    _admin: AuthenticatedUser = Depends(require_admin),
    service: RateLimitConfigService = Depends(get_rate_limit_config_service),
) -> ResetUserUsageResponse:
    """Reset the daily tutor message counter for a specific user."""
    await service.reset_user_usage(user_id)
    logger.info(
        "Admin reset user tutor usage counter",
        admin_email=_admin.email,
        user_id=user_id,
    )
    return ResetUserUsageResponse(
        user_id=user_id,
        message="Daily usage counter has been reset",
    )
