from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class UsageCategory(enum.StrEnum):
    user = "user"
    expert = "expert"
    system = "system"


class RequestType(enum.StrEnum):
    lesson = "lesson"
    quiz = "quiz"
    flashcard = "flashcard"
    case_study = "case_study"
    tutor_chat = "tutor_chat"
    embedding = "embedding"
    rag_indexing = "rag_indexing"
    course_structure = "course_structure"


_usage_category_enum = Enum(
    *[e.value for e in UsageCategory],
    name="usagecategory",
    create_type=False,
)
_request_type_enum = Enum(
    *[e.value for e in RequestType],
    name="requesttype",
    create_type=False,
)


class ApiUsageLog(Base):
    __tablename__ = "api_usage_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="SET NULL"), nullable=True
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id", ondelete="SET NULL"), nullable=True
    )
    usage_category: Mapped[str] = mapped_column(_usage_category_enum)
    request_type: Mapped[str] = mapped_column(_request_type_enum)
    api_provider: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    cost_credits: Mapped[int] = mapped_column(BigInteger)
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
