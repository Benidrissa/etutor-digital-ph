"""Add create_user to adminaction enum.

Revision ID: 065
Revises: 064
"""

from alembic import op

revision = "065"
down_revision = "064"


def upgrade() -> None:
    op.execute("ALTER TYPE adminaction ADD VALUE IF NOT EXISTS 'create_user'")


def downgrade() -> None:
    pass
