"""Admin management schemas."""

from pydantic import BaseModel

from app.domain.models.audit_log import AdminAction
from app.domain.models.user import UserRole


class AdminUserListParams(BaseModel):
    """Query params for listing users."""

    search: str | None = None
    country: str | None = None
    level: int | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    offset: int = 0
    limit: int = 50


class UpdateUserStatusRequest(BaseModel):
    is_active: bool


class AuditLogResponse(BaseModel):
    id: str
    admin_id: str | None
    admin_email: str
    target_user_id: str | None
    target_user_email: str | None
    action: AdminAction
    details: str | None
    created_at: str


class AdminUserListResponse(BaseModel):
    users: list
    total: int
    offset: int
    limit: int
