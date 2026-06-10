"""Make unit_quality_assessments.run_id nullable

The auto post-generation QA path dispatches assess_and_regenerate_unit_task
with no run_id (a standalone per-unit score has no course-level run). The
whole service/task layer already treats run_id as optional, but the column
was created NOT NULL in migration 090, so every auto QA insert hit a
NOT NULL violation and the assessment never persisted (#2456). Relaxing the
constraint aligns the DB with the code's existing run_id-optional intent.

Revision ID: 099_quality_assessment_run_id_nullable
Revises: 098_payment_provider_columns
Create Date: 2026-06-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "099_quality_assessment_run_id_nullable"
down_revision: str | None = "098_payment_provider_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "unit_quality_assessments",
        "run_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Will fail if any run_id IS NULL rows exist (auto-QA assessments) —
    # expected for a relax-then-tighten migration.
    op.alter_column(
        "unit_quality_assessments",
        "run_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
