"""Add brute-force protection columns to totp_secrets.

Revision ID: 018_add_totp_brute_force_protection
Revises: 017_fix_unique_lesson_per_unit_index
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_totp_brute_force_protection"
down_revision: str | None = "017_fix_unique_lesson_per_unit_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "totp_secrets",
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "totp_secrets",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("totp_secrets", "locked_until")
    op.drop_column("totp_secrets", "failed_attempts")
