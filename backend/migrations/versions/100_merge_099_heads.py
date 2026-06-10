"""Merge the two 099 head revisions into a single head

PRs #2456 (099_quality_assessment_run_id_nullable) and #2461
(099_country_kebab_to_iso) were developed and merged concurrently, each
branching off 098_payment_provider_columns. That left the migration graph
with two heads, so `alembic upgrade head` aborts with "Multiple head
revisions are present" and every deploy fails at the migration step (#2475).

This is a no-op merge migration: it has no schema changes, it only unifies
the two heads so there is a single linear head again.

Revision ID: 100_merge_099_heads
Revises: 099_quality_assessment_run_id_nullable, 099_country_kebab_to_iso
Create Date: 2026-06-10
"""

from __future__ import annotations

revision: str = "100_merge_099_heads"
down_revision: tuple[str, str] = (
    "099_quality_assessment_run_id_nullable",
    "099_country_kebab_to_iso",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
