"""Add objectives_json to courses.

Revision ID: 063
Revises: 062
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("objectives_json", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "objectives_json")
