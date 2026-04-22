from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import ARRAY, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.document_chunk import DocumentChunk


class ImageType(enum.StrEnum):
    diagram = "diagram"
    photo = "photo"
    chart = "chart"
    formula = "formula"
    icon = "icon"
    unknown = "unknown"


class SourceImage(Base):
    __tablename__ = "source_images"
    __table_args__ = (
        Index("ix_source_images_semantic_tags_gin", "semantic_tags", postgresql_using="gin"),
        Index("ix_source_images_source_figure", "source", "figure_number"),
        Index("ix_source_images_source_chapter", "source", "chapter"),
        Index("ix_source_images_rag_collection_id", "rag_collection_id"),
        Index("ix_source_images_image_type", "image_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String, nullable=False)
    rag_collection_id: Mapped[str | None] = mapped_column(String, nullable=True)
    figure_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    attribution: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_type: Mapped[str] = mapped_column(
        sa.Enum(
            "diagram",
            "photo",
            "chart",
            "formula",
            "icon",
            "unknown",
            name="source_image_type_enum",
        ),
        server_default="unknown",
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    chapter: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    surrounding_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_key_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_url_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(String(20), server_default="webp", nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    alt_text_fr: Mapped[str | None] = mapped_column(Text, nullable=True)
    alt_text_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_tags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    linked_chunks: Mapped[list[SourceImageChunk]] = relationship(
        "SourceImageChunk",
        back_populates="source_image",
        cascade="all, delete-orphan",
    )

    def to_meta_dict(self) -> dict:
        return {
            "id": str(self.id),
            "source": self.source,
            "rag_collection_id": self.rag_collection_id,
            "figure_number": self.figure_number,
            "caption": self.caption,
            "caption_fr": self.caption_fr,
            "caption_en": self.caption_en,
            "attribution": self.attribution,
            "image_type": self.image_type,
            "page_number": self.page_number,
            "chapter": self.chapter,
            "section": self.section,
            "surrounding_text": self.surrounding_text,
            "storage_key": self.storage_key,
            "storage_url": self.storage_url,
            "storage_key_fr": self.storage_key_fr,
            "storage_url_fr": self.storage_url_fr,
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "file_size_bytes": self.file_size_bytes,
            "original_format": self.original_format,
            "alt_text_fr": self.alt_text_fr,
            "alt_text_en": self.alt_text_en,
            "semantic_tags": self.semantic_tags,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SourceImageChunk(Base):
    __tablename__ = "source_image_chunks"
    __table_args__ = (Index("ix_source_image_chunks_document_chunk_id", "document_chunk_id"),)

    source_image_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_images.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    reference_type: Mapped[str] = mapped_column(
        String(20),
        server_default="contextual",
        nullable=False,
    )

    source_image: Mapped[SourceImage] = relationship(
        "SourceImage",
        back_populates="linked_chunks",
    )
    document_chunk: Mapped[DocumentChunk] = relationship("DocumentChunk")
