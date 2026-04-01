from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.conversation import TutorConversation
    from app.domain.models.module_unit import ModuleUnit
    from app.domain.models.progress import UserModuleProgress
    from app.domain.models.quiz import SummativeAssessmentAttempt


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    module_number: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    level: Mapped[int] = mapped_column(Integer, index=True)
    title_fr: Mapped[str] = mapped_column(Text)
    title_en: Mapped[str] = mapped_column(Text)
    description_fr: Mapped[str | None] = mapped_column(Text)
    description_en: Mapped[str | None] = mapped_column(Text)
    estimated_hours: Mapped[int] = mapped_column(server_default="20")
    bloom_level: Mapped[str | None] = mapped_column(String)
    prereq_modules: Mapped[list | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), server_default="{}"
    )
    books_sources: Mapped[dict | None] = mapped_column(JSON)

    user_progress: Mapped[list[UserModuleProgress]] = relationship(back_populates="module")
    generated_content: Mapped[list[GeneratedContent]] = relationship(back_populates="module")
    tutor_conversations: Mapped[list[TutorConversation]] = relationship(back_populates="module")
    summative_attempts: Mapped[list[SummativeAssessmentAttempt]] = relationship(
        back_populates="module"
    )
    units: Mapped[list[ModuleUnit]] = relationship(back_populates="module")
