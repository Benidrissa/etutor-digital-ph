"""Add setting-related values to adminaction enum.

Revision ID: 021_add_settings_audit_actions
Revises: 020_add_admin_audit_logs_table
Create Date: 2026-04-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "021_add_settings_audit_actions"
down_revision: str | None = "020_add_admin_audit_logs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE adminaction ADD VALUE IF NOT EXISTS "
        "'update_setting'"
    )
    op.execute(
        "ALTER TYPE adminaction ADD VALUE IF NOT EXISTS "
        "'reset_setting'"
    )
    op.execute(
        "ALTER TYPE adminaction ADD VALUE IF NOT EXISTS "
        "'reset_category'"
    )


def downgrade() -> None:
    # Cannot remove values from a PostgreSQL enum.
    pass
