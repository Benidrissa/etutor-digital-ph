"""Add extraction_status column to course_resources.

Revision ID: 069
Revises: 068
Create Date: 2026-04-17

"""

import sqlalchemy as sa
from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "course_resources",
        sa.Column(
            "extraction_status",
            sa.String(10),
            server_default="done",
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE course_resources SET extraction_status = 'done' WHERE extraction_status IS NULL"
    )


def downgrade() -> None:
    op.drop_column("course_resources", "extraction_status")
