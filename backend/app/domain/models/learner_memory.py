from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.user import User


class LearnerMemory(Base):
    __tablename__ = "learner_memory"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    difficulty_domains: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    preferred_explanation_style: Mapped[str | None] = mapped_column(Text)
    preferred_country_examples: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    recurring_questions: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    declared_goals: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    learning_insights: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="learner_memory")
