"""Add ``storage_key_fr`` and ``storage_url_fr`` columns to ``source_images``.

Revision ID: 079
Revises: 078
Create Date: 2026-04-22

Per issue #1834 (epic #1819, Phase 2 slice 1) — per-locale figure-asset
plumbing. Today every figure on ``source_images`` has a single
``storage_key`` / ``storage_url`` pair pointing at the raw PDF-extracted
WebP. Phase 2 will produce French-variant assets (re-derived SVGs,
overlaid raster, etc.) for figures whose in-image text matters.

This migration adds the two nullable columns where those future variants
will land. No code in this migration populates them — subsequent Phase 2
slices (classifier + SVG renderer + overlay compositor) do that.
"""

import sqlalchemy as sa
from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_images",
        sa.Column("storage_key_fr", sa.Text(), nullable=True),
    )
    op.add_column(
        "source_images",
        sa.Column("storage_url_fr", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_images", "storage_url_fr")
    op.drop_column("source_images", "storage_key_fr")
