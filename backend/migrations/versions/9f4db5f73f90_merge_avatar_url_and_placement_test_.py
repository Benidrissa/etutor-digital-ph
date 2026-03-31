"""merge avatar_url and placement_test branches

Revision ID: 9f4db5f73f90
Revises: 008_add_avatar_url, 010_add_placement_test_attempts_table
Create Date: 2026-03-31 15:13:51.666174
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "9f4db5f73f90"
down_revision: str | None = ("008_add_avatar_url", "010_add_placement_test_attempts_table")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
