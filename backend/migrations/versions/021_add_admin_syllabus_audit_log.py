"""Add admin_syllabus_audit_log table for modification history.

Revision ID: 021_add_admin_syllabus_audit_log
Revises: 019_hash_email_otp_codes
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_add_admin_syllabus_audit_log"
down_revision: str | None = "019_hash_email_otp_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_syllabus_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_id", sa.String(), nullable=False),
        sa.Column("admin_email", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module_number", sa.Integer(), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_syllabus_audit_module_id",
        "admin_syllabus_audit_log",
        ["module_id"],
    )
    op.create_index(
        "idx_syllabus_audit_admin_id",
        "admin_syllabus_audit_log",
        ["admin_id"],
    )
    op.create_index(
        "idx_syllabus_audit_created_at",
        "admin_syllabus_audit_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_syllabus_audit_created_at", table_name="admin_syllabus_audit_log")
    op.drop_index("idx_syllabus_audit_admin_id", table_name="admin_syllabus_audit_log")
    op.drop_index("idx_syllabus_audit_module_id", table_name="admin_syllabus_audit_log")
    op.drop_table("admin_syllabus_audit_log")
