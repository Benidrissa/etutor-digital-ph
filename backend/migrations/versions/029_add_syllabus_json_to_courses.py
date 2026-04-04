"""add syllabus_json to courses

Revision ID: 029
Revises: 028
Create Date: 2026-04-04

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("syllabus_json", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("courses", "syllabus_json")
