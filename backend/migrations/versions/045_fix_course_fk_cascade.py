"""Fix FK ondelete for user_course_enrollment and modules to CASCADE on course delete.

Revision ID: 045
Revises: 043
Create Date: 2026-04-07

"""

import sqlalchemy as sa
from alembic import op

revision = "045"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Fix user_course_enrollment.course_id: RESTRICT → CASCADE
    # The original FK was created with raw SQL (no ON DELETE clause → RESTRICT default).
    # This crashes delete_course even when 0 enrollment rows exist.
    op.drop_constraint(
        "user_course_enrollment_course_id_fkey",
        "user_course_enrollment",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_course_enrollment_course_id_fkey",
        "user_course_enrollment",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Fix modules.course_id: SET NULL → CASCADE
    # Drafts-only modules have no standalone value; orphaning them is wrong.
    op.drop_constraint("modules_course_id_fkey", "modules", type_="foreignkey")
    op.create_foreign_key(
        "modules_course_id_fkey",
        "modules",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("modules_course_id_fkey", "modules", type_="foreignkey")
    op.create_foreign_key(
        "modules_course_id_fkey",
        "modules",
        "courses",
        ["course_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "user_course_enrollment_course_id_fkey",
        "user_course_enrollment",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "user_course_enrollment_course_id_fkey",
        "user_course_enrollment",
        "courses",
        ["course_id"],
        ["id"],
    )
