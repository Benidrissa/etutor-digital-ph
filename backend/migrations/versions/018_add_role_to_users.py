"""Add role column to users table.

Revision ID: 018_add_role_to_users
Revises: 011_add_email_otps_table
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_role_to_users"
down_revision: str | None = "011_add_email_otps_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    columns = [c["name"] for c in sa.inspect(conn).get_columns("users")]
    if "role" in columns:
        return

    op.execute("CREATE TYPE IF NOT EXISTS userrole AS ENUM ('user', 'expert', 'admin')")
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("user", "expert", "admin", name="userrole"),
            server_default="user",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "role")
    op.execute("DROP TYPE userrole")
