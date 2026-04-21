from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.content import GeneratedContent
    from app.domain.models.conversation import TutorConversation
    from app.domain.models.course import Course
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
    learning_objectives_fr: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    learning_objectives_en: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quiz_topics_fr: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    quiz_topics_en: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    flashcard_categories_fr: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    flashcard_categories_en: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    case_study_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_study_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    user_progress: Mapped[list[UserModuleProgress]] = relationship(
        back_populates="module", passive_deletes=True
    )
    generated_content: Mapped[list[GeneratedContent]] = relationship(
        back_populates="module", passive_deletes=True
    )
    tutor_conversations: Mapped[list[TutorConversation]] = relationship(
        back_populates="module", passive_deletes=True
    )
    summative_attempts: Mapped[list[SummativeAssessmentAttempt]] = relationship(
        back_populates="module", passive_deletes=True
    )
    units: Mapped[list[ModuleUnit]] = relationship(back_populates="module", passive_deletes=True)
    course: Mapped[Course | None] = relationship(back_populates="modules")
