"""Add avatar_url to users table

Revision ID: 008_add_avatar_url
Revises: 09a53bdc050e
Create Date: 2026-03-31 03:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008_add_avatar_url"
down_revision: str | None = "09a53bdc050e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add avatar_url column to users table."""
    op.add_column("users", sa.Column("avatar_url", sa.String(), nullable=True))


def downgrade() -> None:
    """Remove avatar_url column from users table."""
    op.drop_column("users", "avatar_url")
