"""Add lesson_id index to generated_images for dedup queries.

Revision ID: 058
Revises: 057
Create Date: 2026-04-11

"""

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_generated_images_lesson_id ON generated_images (lesson_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_generated_images_lesson_id", table_name="generated_images")
