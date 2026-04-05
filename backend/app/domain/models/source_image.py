"""Domain models for source images extracted from reference PDFs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.document_chunk import DocumentChunk


class SourceImage(Base):
    """
    Represents an image extracted from a reference PDF (RAG source).

    Stores metadata about figures/diagrams found in the 3 reference textbooks,
    used to enrich RAG responses with visual content.
    """

    __tablename__ = "source_images"
    __table_args__ = (
        Index("ix_source_images_source", "source"),
        Index("ix_source_images_page_number", "page_number"),
        Index("ix_source_images_figure_number", "figure_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(String, nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    figure_number: Mapped[str | None] = mapped_column(String, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="unknown")
    surrounding_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    chunk_links: Mapped[list[SourceImageChunk]] = relationship(
        "SourceImageChunk",
        back_populates="image",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<SourceImage(id={self.id}, source='{self.source}', "
            f"page={self.page_number}, figure='{self.figure_number}')>"
        )


class SourceImageChunk(Base):
    """
    Junction table linking SourceImage records to DocumentChunk records.

    Two link types:
    - explicit: chunk text contains a "Figure X.Y" reference matching the image
    - contextual: chunk and image share the same page number (proximity-based)
    """

    __tablename__ = "source_image_chunks"
    __table_args__ = (
        UniqueConstraint(
            "image_id",
            "chunk_id",
            name="uq_source_image_chunks_image_chunk",
        ),
        Index("ix_source_image_chunks_image_id", "image_id"),
        Index("ix_source_image_chunks_chunk_id", "chunk_id"),
        Index("ix_source_image_chunks_reference_type", "reference_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_images.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    reference_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    image: Mapped[SourceImage] = relationship(
        "SourceImage",
        back_populates="chunk_links",
    )
    chunk: Mapped[DocumentChunk] = relationship("DocumentChunk")

    def __repr__(self) -> str:
        return (
            f"<SourceImageChunk(image_id={self.image_id}, "
            f"chunk_id={self.chunk_id}, type='{self.reference_type}')>"
        )
