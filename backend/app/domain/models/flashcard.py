from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.user import User


class FlashcardReview(Base):
    __tablename__ = "flashcard_reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("generated_content.id"), index=True)
    rating: Mapped[str] = mapped_column(String)  # again|hard|good|easy
    next_review: Mapped[datetime] = mapped_column(index=True)
    stability: Mapped[float] = mapped_column(server_default="1.0")
    difficulty: Mapped[float] = mapped_column(server_default="5.0")
    reviewed_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped[User] = relationship(back_populates="flashcard_reviews")
    card: Mapped[GeneratedContent] = relationship(back_populates="flashcard_reviews")
