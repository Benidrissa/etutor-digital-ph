"""add image_hash to source_images for cross-course dedup

Revision ID: 095_add_image_hash_to_source_images
Revises: 094_fix_generated_images_fk_set_null
Create Date: 2026-05-16

Persists a 16-char hex 64-bit average-hash for each source image so the RAG
pipeline can detect cross-course duplicates and reuse existing MinIO objects,
OpenAI embeddings, and Claude translations instead of recomputing them.

The hash is derived from the same avg-hash algorithm already used for within-PDF
deduplication in PDFImageExtractor._deduplicate_images(). No UNIQUE constraint:
the copy-on-write model stores one row per course but reuses the expensive fields.
"""

import sqlalchemy as sa
from alembic import op

revision: str = "095_add_image_hash_to_source_images"
down_revision: str | None = "094_fix_generated_images_fk_set_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_images",
        sa.Column("image_hash", sa.String(16), nullable=True),
    )
    op.create_index(
        "ix_source_images_image_hash",
        "source_images",
        ["image_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_images_image_hash", table_name="source_images")
    op.drop_column("source_images", "image_hash")
