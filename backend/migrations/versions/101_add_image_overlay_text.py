"""Add overlay text columns to generated_images

Text-free illustrations (#2512) render their title and component labels as real
DOM text on top of the image instead of baking garbled text into the pixels.
These columns carry that bilingual overlay text per image.

Revision ID: 101_add_image_overlay_text
Revises: 100_merge_099_heads
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "101_add_image_overlay_text"
down_revision: str | None = "100_merge_099_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("generated_images", sa.Column("title_fr", sa.Text(), nullable=True))
    op.add_column("generated_images", sa.Column("title_en", sa.Text(), nullable=True))
    op.add_column("generated_images", sa.Column("overlay_labels", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("generated_images", "overlay_labels")
    op.drop_column("generated_images", "title_en")
    op.drop_column("generated_images", "title_fr")
