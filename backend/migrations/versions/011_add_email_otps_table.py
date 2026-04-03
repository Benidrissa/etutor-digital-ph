"""Add email_otps table

Revision ID: 011_add_email_otps_table
Revises: 017_fix_unique_lesson_per_unit_index
Create Date: 2026-04-01 05:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_add_email_otps_table"
down_revision: str | None = "017_fix_unique_lesson_per_unit_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create email_otps table
    op.create_table(
        "email_otps",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),  # Nullable for registration flow
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),  # "registration" or "login"
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_email_otps_user_id"), "email_otps", ["user_id"], unique=False)
    op.create_index(op.f("ix_email_otps_email"), "email_otps", ["email"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_otps_email"), table_name="email_otps")
    op.drop_index(op.f("ix_email_otps_user_id"), table_name="email_otps")
    op.drop_table("email_otps")
