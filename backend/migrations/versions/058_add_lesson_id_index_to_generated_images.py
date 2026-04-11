"""Add lesson_id index to generated_images for dedup queries.

Revision ID: 057
Revises: 056
Create Date: 2026-04-11

"""

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_generated_images_lesson_id",
        "generated_images",
        ["lesson_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_generated_images_lesson_id", table_name="generated_images")
