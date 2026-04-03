"""Add image_data BYTEA column to generated_images for persistent binary storage

Revision ID: 016_add_image_data_bytea
Revises: 015_add_generated_images_table
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "016_add_image_data_bytea"
down_revision: str | None = "015_add_generated_images_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = [c["name"] for c in sa.inspect(conn).get_columns("generated_images")]
    if "image_data" in columns:
        return

    op.add_column(
        "generated_images",
        sa.Column("image_data", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generated_images", "image_data")
