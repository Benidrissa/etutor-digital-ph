"""Make admin_audit_logs.admin_email nullable for phone-only admins.

Revision ID: 054
Revises: 053
Create Date: 2026-04-10

"""

import sqlalchemy as sa
from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.scalar() is not None


def upgrade() -> None:
    if _column_exists("admin_audit_logs", "admin_email"):
        op.alter_column("admin_audit_logs", "admin_email", nullable=True)
    else:
        op.add_column(
            "admin_audit_logs",
            sa.Column("admin_email", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("admin_audit_logs", "admin_email"):
        op.execute("UPDATE admin_audit_logs SET admin_email = 'unknown' WHERE admin_email IS NULL")
        op.alter_column("admin_audit_logs", "admin_email", nullable=False)
