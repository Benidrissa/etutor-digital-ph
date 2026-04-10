"""Make admin_audit_logs.admin_email nullable for phone-only admins.

Revision ID: 054
Revises: 053
Create Date: 2026-04-10

"""

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("admin_audit_logs", "admin_email", nullable=True)


def downgrade() -> None:
    op.execute(
        "UPDATE admin_audit_logs SET admin_email = 'unknown' WHERE admin_email IS NULL"
    )
    op.alter_column("admin_audit_logs", "admin_email", nullable=False)
