"""Merge email_otps and module_units branches

Revision ID: 013_merge_email_otps_and_module_units
Revises: 011_add_email_otps_table, 012_invalidate_m01_m03_cached_lessons
Create Date: 2026-04-02 00:25:00.000000
"""

from collections.abc import Sequence

revision: str = "013_merge_email_otps_and_module_units"
down_revision: str | None = ("011_add_email_otps_table", "012_invalidate_m01_m03_cached_lessons")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
