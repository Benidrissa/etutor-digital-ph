"""Domain models for source images extracted from reference PDFs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ARRAY, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base


class SourceImage(Base):
    """Represents an image extracted from a reference PDF (donaldson, triola, scutchfield).

    Stores WebP binary data in S3 and rich metadata (figure number, caption, attribution)
    to support RAG image retrieval and frontend display.
    """

    __tablename__ = "source_images"
    __table_args__ = (
        Index("ix_source_images_source", "source"),
        Index("ix_source_images_rag_collection_id", "rag_collection_id"),
        Index("ix_source_images_image_type", "image_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(String, nullable=False)
    rag_collection_id: Mapped[str | None] = mapped_column(String, nullable=True)

    figure_number: Mapped[str | None] = mapped_column(String, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_type: Mapped[str] = mapped_column(
        sa.Enum(
            "diagram",
            "chart",
            "photo",
            "formula",
            "icon",
            "unknown",
            name="source_image_type_enum",
        ),
        nullable=False,
        server_default="unknown",
    )

    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)

    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    alt_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)

    surrounding_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    extra_meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    chunk_links: Mapped[list[SourceImageChunk]] = relationship(
        "SourceImageChunk",
        back_populates="image",
        cascade="all, delete-orphan",
    )

    def to_meta_dict(self) -> dict[str, Any]:
        """Return metadata dict (no binary data) suitable for API responses."""
        return {
            "id": str(self.id),
            "source": self.source,
            "rag_collection_id": self.rag_collection_id,
            "figure_number": self.figure_number,
            "caption": self.caption,
            "attribution": self.attribution,
            "image_type": self.image_type,
            "page_number": self.page_number,
            "chapter": self.chapter,
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "storage_url": self.storage_url,
            "alt_text_fr": self.alt_text_fr,
            "alt_text_en": self.alt_text_en,
        }


class SourceImageChunk(Base):
    """Junction table linking source images to document chunks.

    Supports two reference types:
    - explicit: figure is directly referenced in the chunk text
    - contextual: image appears on the same page/section as the chunk
    """

    __tablename__ = "source_image_chunks"
    __table_args__ = (
        Index("ix_source_image_chunks_chunk_id", "chunk_id"),
        Index("ix_source_image_chunks_image_id", "image_id"),
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
        sa.Enum("explicit", "contextual", name="image_chunk_reference_type_enum"),
        nullable=False,
        server_default="contextual",
    )

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    image: Mapped[SourceImage] = relationship(
        "SourceImage",
        back_populates="chunk_links",
    )
