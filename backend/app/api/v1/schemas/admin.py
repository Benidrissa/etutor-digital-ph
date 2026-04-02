"""Pydantic schemas for admin rate limit management endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GlobalRateLimitResponse(BaseModel):
    daily_limit: int = Field(..., description="Global daily tutor message limit")


class UpdateGlobalRateLimitRequest(BaseModel):
    daily_limit: int = Field(..., ge=1, le=10000, description="New global daily limit (1–10000)")


class UserRateLimitOverrideResponse(BaseModel):
    user_id: str
    override_limit: int | None
    usage_today: int
    effective_limit: int


class SetUserRateLimitRequest(BaseModel):
    daily_limit: int = Field(..., ge=1, le=10000, description="Per-user daily limit (1–10000)")


class UserUsageResponse(BaseModel):
    user_id: str
    usage_today: int
    effective_limit: int
    override_limit: int | None


class UsageListResponse(BaseModel):
    users: list[UserUsageResponse]
    global_limit: int


class ResetUserUsageResponse(BaseModel):
    user_id: str
    message: str
