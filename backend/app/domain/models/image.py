from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id"), nullable=True, index=True
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id"), nullable=False, index=True
    )
    unit_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    dalle_prompt: Mapped[str | None] = mapped_column(String, nullable=True)
    semantic_tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True, server_default="{}"
    )
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    alt_text_fr: Mapped[str | None] = mapped_column(String, nullable=True)
    alt_text_en: Mapped[str | None] = mapped_column(String, nullable=True)
    reuse_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
