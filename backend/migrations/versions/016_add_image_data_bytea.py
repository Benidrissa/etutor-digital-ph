"""Add image_data BYTEA column to generated_images for storing WebP bytes.

Revision ID: 016_add_image_data_bytea
Revises: 015_add_generated_images_table
Create Date: 2026-04-03

"""

from alembic import op
import sqlalchemy as sa

revision = "016_add_image_data_bytea"
down_revision = "015_add_generated_images_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_images",
        sa.Column("image_data", sa.LargeBinary, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generated_images", "image_data")
