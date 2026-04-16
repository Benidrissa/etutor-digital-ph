"""Add organization_id to courses for org-scoped course creation.

Revision ID: 066
Revises: 065
Create Date: 2026-04-14

"""

import sqlalchemy as sa
from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_courses_organization_id",
        "courses",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_courses_organization_id", "courses", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_courses_organization_id", "courses")
    op.drop_constraint("fk_courses_organization_id", "courses", type_="foreignkey")
    op.drop_column("courses", "organization_id")
