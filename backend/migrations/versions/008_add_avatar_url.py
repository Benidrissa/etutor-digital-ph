"""Add avatar_url to users table

Revision ID: 008_add_avatar_url
Revises: 09a53bdc050e
Create Date: 2026-03-31 03:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_add_avatar_url'
down_revision: Union[str, None] = '09a53bdc050e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add avatar_url column to users table."""
    op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove avatar_url column from users table."""
    op.drop_column('users', 'avatar_url')