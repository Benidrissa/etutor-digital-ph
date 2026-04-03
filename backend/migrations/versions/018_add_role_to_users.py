"""Add role ENUM column to users table.

Revision ID: 018_add_role_to_users
Revises: 017_fix_unique_lesson_per_unit_index
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "018_add_role_to_users"
down_revision: str | None = "017_fix_unique_lesson_per_unit_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE userrole AS ENUM ('user', 'expert', 'admin')")

    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("user", "expert", "admin", name="userrole"),
            server_default="user",
            nullable=False,
        ),
    )

    op.execute("UPDATE users SET role = 'user' WHERE role IS NULL")


def downgrade() -> None:
    op.drop_column("users", "role")
    op.execute("DROP TYPE IF EXISTS userrole")
