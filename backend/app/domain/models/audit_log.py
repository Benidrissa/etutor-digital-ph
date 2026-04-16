from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.user import User


class AdminAction(enum.StrEnum):
    deactivate_user = "deactivate_user"
    reactivate_user = "reactivate_user"
    promote_to_expert = "promote_to_expert"
    promote_to_admin = "promote_to_admin"
    demote_to_user = "demote_to_user"
    update_role = "update_role"
    update_setting = "update_setting"
    reset_setting = "reset_setting"
    reset_category = "reset_category"
    delete_course = "delete_course"
    create_user = "create_user"


class AuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    admin_email: Mapped[str | None] = mapped_column(String, nullable=True)
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_user_email: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[AdminAction] = mapped_column(Enum(AdminAction, name="adminaction"))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    admin: Mapped[User | None] = relationship(
        "User", foreign_keys=[admin_id], primaryjoin="AuditLog.admin_id == User.id"
    )
    target_user: Mapped[User | None] = relationship(
        "User", foreign_keys=[target_user_id], primaryjoin="AuditLog.target_user_id == User.id"
    )
