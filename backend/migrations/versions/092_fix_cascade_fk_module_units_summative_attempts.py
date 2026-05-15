"""fix ON DELETE CASCADE on module_units and summative_assessment_attempts

Revision ID: 092_fix_cascade_fk_module_units_summative_attempts
Revises: 091_relax_module_progress_locked_post_2125
Create Date: 2026-05-15

Both tables were created without ondelete in their FK constraints (defaulting to
RESTRICT), while the SQLAlchemy models specify ondelete="CASCADE". This mismatch
causes course deletion to fail because PostgreSQL blocks module row deletion.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "092_fix_cascade_fk_module_units_summative_attempts"
down_revision: str | None = "091_relax_module_progress_locked_post_2125"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # module_units.module_id → modules.id
    op.drop_constraint("module_units_module_id_fkey", "module_units", type_="foreignkey")
    op.create_foreign_key(
        "module_units_module_id_fkey",
        "module_units",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # summative_assessment_attempts.module_id → modules.id
    op.drop_constraint(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # summative_assessment_attempts.assessment_id → generated_content.id
    op.drop_constraint(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        "generated_content",
        ["assessment_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        "generated_content",
        ["assessment_id"],
        ["id"],
    )

    op.drop_constraint(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        "modules",
        ["module_id"],
        ["id"],
    )

    op.drop_constraint("module_units_module_id_fkey", "module_units", type_="foreignkey")
    op.create_foreign_key(
        "module_units_module_id_fkey",
        "module_units",
        "modules",
        ["module_id"],
        ["id"],
    )
