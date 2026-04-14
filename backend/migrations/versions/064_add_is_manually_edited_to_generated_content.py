"""Add is_manually_edited to generated_content.

Revision ID: 064
Revises: 063
Create Date: 2026-04-14

"""

from alembic import op
import sqlalchemy as sa

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_content",
        sa.Column("is_manually_edited", sa.Boolean, server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("generated_content", "is_manually_edited")
