"""Domain model for per-chunk PDF summaries — enables resilient retry of syllabus generation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from .base import Base


class ChunkSummary(Base):
    """Stores Claude-generated summaries for individual PDF chunks.

    Allows syllabus generation to resume mid-summarization without
    re-calling the API for already-completed chunks.
    """

    __tablename__ = "chunk_summaries"
    __table_args__ = (
        UniqueConstraint("course_id", "book_name", "chunk_index", name="uq_chunk_summary"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    book_name: Mapped[str] = mapped_column(String(512), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

