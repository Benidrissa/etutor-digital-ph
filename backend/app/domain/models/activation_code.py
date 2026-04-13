from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course
    from app.domain.models.credit import CreditTransaction
    from app.domain.models.curriculum import Curriculum
    from app.domain.models.organization import Organization
    from app.domain.models.user import User


class ActivationCode(Base):
    __tablename__ = "activation_codes"
    __table_args__ = (
        CheckConstraint(
            "(course_id IS NOT NULL) OR (curriculum_id IS NOT NULL)",
            name="ck_activation_codes_course_or_curriculum",
        ),
        CheckConstraint(
            "(organization_id IS NULL) OR (created_by IS NULL)",
            name="ck_activation_codes_org_xor_expert",
        ),
        CheckConstraint(
            "(curriculum_id IS NULL) OR (organization_id IS NOT NULL)",
            name="ck_activation_codes_curriculum_requires_org",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True, index=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    curriculum_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("curricula.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    times_used: Mapped[int] = mapped_column(Integer, server_default="0", default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true", default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    course: Mapped[Course | None] = relationship()
    organization: Mapped[Organization | None] = relationship(foreign_keys=[organization_id])
    curriculum: Mapped[Curriculum | None] = relationship(foreign_keys=[curriculum_id])
    creator: Mapped[User | None] = relationship(foreign_keys=[created_by])
    redemptions: Mapped[list[ActivationCodeRedemption]] = relationship(back_populates="code")


class ActivationCodeRedemption(Base):
    __tablename__ = "activation_code_redemptions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("activation_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    redeemed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    activated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    credit_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="SET NULL"), nullable=True
    )

    code: Mapped[ActivationCode] = relationship(back_populates="redemptions")
    user: Mapped[User] = relationship(foreign_keys=[user_id])
    activator: Mapped[User | None] = relationship(foreign_keys=[activated_by])
    credit_transaction: Mapped[CreditTransaction | None] = relationship()

    __table_args__ = (
        UniqueConstraint("code_id", "user_id", name="uq_activation_code_redemptions_code_user"),
        Index("ix_activation_code_redemptions_code_id_user_id", "code_id", "user_id"),
    )
