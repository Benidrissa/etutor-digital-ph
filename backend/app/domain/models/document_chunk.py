"""Domain model for document chunks in the RAG pipeline."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ARRAY, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class DocumentChunk(Base):
    """
    Represents a chunked piece of text from source documents for RAG retrieval.

    Used to store 512-token chunks from reference PDFs with embeddings for
    semantic similarity search in the RAG pipeline.
    """

    __tablename__ = "document_chunks"

    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Content and embedding
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)

    # Source metadata
    source: Mapped[str] = mapped_column(String, nullable=False)  # "donaldson", "triola", etc.
    chapter: Mapped[str | None] = mapped_column(String, nullable=True)  # "chapter_3"
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1-4 difficulty
    language: Mapped[str] = mapped_column(String(2), nullable=False)  # "fr" or "en"

    # Chunk metadata
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)  # Order within source

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk(id={self.id}, source='{self.source}', "
            f"chapter='{self.chapter}', tokens={self.token_count})>"
        )

    @property
    def preview(self) -> str:
        """Return first 100 characters of content for preview."""
        return self.content[:100] + "..." if len(self.content) > 100 else self.content

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "id": str(self.id),
            "content": self.content,
            "source": self.source,
            "chapter": self.chapter,
            "page": self.page,
            "level": self.level,
            "language": self.language,
            "token_count": self.token_count,
            "chunk_index": self.chunk_index,
            "created_at": self.created_at.isoformat(),
            "preview": self.preview,
        }
