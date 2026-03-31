"""Authentication models for TOTP MFA and refresh tokens."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.user import User


class TOTPSecret(Base):
    """TOTP secret for two-factor authentication."""

    __tablename__ = "totp_secrets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    secret: Mapped[str] = mapped_column(String(32))  # Base32 encoded secret
    backup_codes: Mapped[str | None] = mapped_column(Text)  # JSON array of backup codes
    is_verified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="totp_secret")


class RefreshToken(Base):
    """Refresh token for JWT authentication."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # SHA-256 hash
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(500))
    ip_address: Mapped[str | None] = mapped_column(String(45))  # IPv6 support

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class MagicLink(Base):
    """Magic link for account recovery."""

    __tablename__ = "magic_links"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)  # SHA-256 hash
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(45))

    user: Mapped[User] = relationship(back_populates="magic_links")
