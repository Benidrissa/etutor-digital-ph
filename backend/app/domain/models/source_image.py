"""Domain model for images extracted from reference PDF sources."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.document_chunk import DocumentChunk


class SourceImage(Base):
    """Image extracted from a reference PDF source for RAG integration."""

    __tablename__ = "source_images"
    __table_args__ = (
        Index("ix_source_images_source", "source"),
        Index("ix_source_images_page_number", "page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(String, nullable=False)
    rag_collection_id: Mapped[str | None] = mapped_column(String, nullable=True)

    storage_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    storage_url: Mapped[str] = mapped_column(Text, nullable=False)

    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    figure_number: Mapped[str | None] = mapped_column(String, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="unknown")
    surrounding_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    chapter: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)

    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_format: Mapped[str] = mapped_column(String(20), nullable=False, server_default="png")

    caption_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    chunks: Mapped[list[DocumentChunk]] = relationship(
        "DocumentChunk",
        secondary="source_image_chunks",
        back_populates="images",
        lazy="select",
    )


class SourceImageChunk(Base):
    """Junction table linking source images to document chunks."""

    __tablename__ = "source_image_chunks"

    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_images.id", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
