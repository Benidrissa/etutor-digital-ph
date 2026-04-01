from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(index=True, nullable=True)
    module_id: Mapped[uuid.UUID] = mapped_column(index=True)
    unit_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String(20), index=True, server_default="pending")
    dalle_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    key_concept: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_data: Mapped[bytes | None] = mapped_column(nullable=True)
    alt_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    reuse_count: Mapped[int] = mapped_column(Integer, server_default="0")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
