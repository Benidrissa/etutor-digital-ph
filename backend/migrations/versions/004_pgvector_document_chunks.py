"""Add pgvector extension and document_chunks table for RAG pipeline.

Revision ID: 004_pgvector_document_chunks
Revises: 003_seed_modules
Create Date: 2026-03-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004_pgvector_document_chunks"
down_revision: str | None = "003_seed_modules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create document_chunks table for RAG pipeline
    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float), nullable=True),
        sa.Column("source", sa.String(), nullable=False),  # e.g., "donaldson", "triola"
        sa.Column("chapter", sa.String(), nullable=True),  # e.g., "chapter_3"
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=True),  # 1-4 for difficulty targeting
        sa.Column("language", sa.String(2), nullable=False),  # "fr" or "en"
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),  # Order within source
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Create indexes for efficient retrieval
    op.create_index("idx_document_chunks_source", "document_chunks", ["source"])
    op.create_index("idx_document_chunks_level", "document_chunks", ["level"])
    op.create_index("idx_document_chunks_language", "document_chunks", ["language"])
    op.create_index("idx_document_chunks_chapter", "document_chunks", ["chapter"])

    # Note: HNSW index will be created after embeddings are populated
    # This is commented out as it requires embeddings to exist
    # op.execute(
    #     "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_document_chunks_embedding_hnsw "
    #     "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
    #     "WITH (m = 16, ef_construction = 64)"
    # )


def downgrade() -> None:
    # Drop HNSW index first
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw")

    # Drop table
    op.drop_table("document_chunks")

    # Note: We don't drop the vector extension as other tables might use it
