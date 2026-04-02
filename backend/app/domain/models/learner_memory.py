from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.user import User


class LearnerMemory(Base):
    __tablename__ = "learner_memory"
    __table_args__ = (UniqueConstraint("user_id", name="uq_learner_memory_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    difficulty_domains: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    preferred_explanation_style: Mapped[str | None] = mapped_column(String(100))
    preferred_country_examples: Mapped[list[str]] = mapped_column(
        ARRAY(String), server_default="{}"
    )
    recurring_questions: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    declared_goals: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    learning_insights: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="learner_memory")
