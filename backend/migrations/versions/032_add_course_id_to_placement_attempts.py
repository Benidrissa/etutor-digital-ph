"""add course_id to placement_test_attempts

Revision ID: 032
Revises: 031
Create Date: 2026-04-05

"""

import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "placement_test_attempts",
        sa.Column(
            "course_id",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_placement_test_attempts_course_id",
        "placement_test_attempts",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_placement_test_attempts_course_id",
        "placement_test_attempts",
        ["course_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_placement_test_attempts_course_id", table_name="placement_test_attempts")
    op.drop_constraint(
        "fk_placement_test_attempts_course_id", "placement_test_attempts", type_="foreignkey"
    )
    op.drop_column("placement_test_attempts", "course_id")
