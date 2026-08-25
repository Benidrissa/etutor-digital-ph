"""convert embedding columns float[] -> vector(1536) and add HNSW indexes

Revision ID: 105_vector_embedding_columns_hnsw
Revises: 104_add_ai_usage_events
Create Date: 2026-07-11

document_chunks.embedding and source_images.embedding were stored as
``double precision[]`` (SQLAlchemy ARRAY(Float)) since migration 004, and the
HNSW index that 004 planned was never created — so every semantic search cast
``embedding::vector`` per row and cosine-scored the *entire* collection with a
sequential scan (#2635).

This migration converts both columns to native pgvector ``vector(1536)`` and
builds an HNSW ``vector_cosine_ops`` index on each, so
``ORDER BY embedding <=> :q LIMIT k`` becomes index-backed.

Cast path: pgvector registers only a ``real[] -> vector`` cast, so we go
``double precision[]::real[]::vector``. NULL embeddings stay NULL. All
populated rows are 1536-dim (OpenAI text-embedding-3-small), so the cast into
the dimension-typed column is total.

WARNING: ``ALTER COLUMN ... TYPE`` rewrites each table under an ACCESS
EXCLUSIVE lock, and the HNSW build is non-concurrent here. Embeddings are
effectively append-only, so run this inside a deploy/maintenance window.
Measure row counts + timing on staging first (#2635 rollout note). If prod
table sizes make the lock unacceptable, switch to the add-column / batch
backfill / swap variant and build the index CONCURRENTLY out-of-band.
"""

from alembic import op

revision: str = "105_vector_embedding_columns_hnsw"
down_revision: str | None = "104_add_ai_usage_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector was enabled in migration 004; keep idempotent for safety.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::real[]::vector"
    )
    op.execute(
        "ALTER TABLE source_images "
        "ALTER COLUMN embedding TYPE vector(1536) "
        "USING embedding::real[]::vector"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw "
        "ON document_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_images_embedding_hnsw "
        "ON source_images USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_source_images_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw")

    # vector -> real[] cast is registered by pgvector; widen to double precision[]
    # to restore the original ARRAY(Float) column type.
    op.execute(
        "ALTER TABLE source_images "
        "ALTER COLUMN embedding TYPE double precision[] "
        "USING embedding::real[]::double precision[]"
    )
    op.execute(
        "ALTER TABLE document_chunks "
        "ALTER COLUMN embedding TYPE double precision[] "
        "USING embedding::real[]::double precision[]"
    )
