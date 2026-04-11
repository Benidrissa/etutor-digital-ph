"""Add sub_admin value to userrole enum.

Revision ID: 056
Revises: 055
Create Date: 2026-04-11

"""

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'sub_admin' BEFORE 'admin'")


def downgrade() -> None:
    pass
