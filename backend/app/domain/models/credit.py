from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BIGINT,
    NUMERIC,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.organization import Organization
    from app.domain.models.user import User


class TransactionType(enum.StrEnum):
    credit_purchase = "credit_purchase"
    content_access = "content_access"
    tutor_usage = "tutor_usage"
    offline_download = "offline_download"
    course_purchase = "course_purchase"
    course_earning = "course_earning"
    commission = "commission"
    expert_activation = "expert_activation"
    generation_cost = "generation_cost"
    payout = "payout"
    refund = "refund"
    free_trial = "free_trial"
    org_code_escrow = "org_code_escrow"
    org_code_refund = "org_code_refund"
    org_credit_purchase = "org_credit_purchase"


class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    __table_args__ = (
        Index(
            "ix_credit_accounts_user_id_unique",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "ix_credit_accounts_organization_id_unique",
            "organization_id",
            unique=True,
            postgresql_where=text("organization_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    balance: Mapped[int] = mapped_column(BIGINT, server_default="0", default=0)
    total_purchased: Mapped[int] = mapped_column(BIGINT, server_default="0", default=0)
    total_spent: Mapped[int] = mapped_column(BIGINT, server_default="0", default=0)
    total_earned: Mapped[int] = mapped_column(BIGINT, server_default="0", default=0)
    total_withdrawn: Mapped[int] = mapped_column(BIGINT, server_default="0", default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User | None] = relationship(back_populates="credit_account")
    organization: Mapped[Organization | None] = relationship(foreign_keys=[organization_id])
    transactions: Mapped[list[CreditTransaction]] = relationship(
        back_populates="account", order_by="CreditTransaction.created_at.desc()"
    )


class CreditTransaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("credit_accounts.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transactiontype"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BIGINT, nullable=False)
    balance_after: Mapped[int] = mapped_column(BIGINT, nullable=False)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    account: Mapped[CreditAccount] = relationship(back_populates="transactions")

    __table_args__ = (Index("ix_transactions_account_id_created_at", "account_id", "created_at"),)


class CreditPackage(Base):
    __tablename__ = "credit_packages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name_fr: Mapped[str] = mapped_column(String, nullable=False)
    name_en: Mapped[str] = mapped_column(String, nullable=False)
    credits: Mapped[int] = mapped_column(BIGINT, nullable=False)
    price_xof: Mapped[int] = mapped_column(BIGINT, nullable=False)
    price_usd: Mapped[float] = mapped_column(NUMERIC(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    sort_order: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
