"""Merge module_units and email_otps branches

Revision ID: 012_merge_module_units_and_email_otps
Revises: 0d1135672916, 011_add_email_otps_table
Create Date: 2026-04-01 14:44:00.000000

"""

from collections.abc import Sequence

revision: str = "012_merge_module_units_and_email_otps"
down_revision: tuple[str, str] = ("0d1135672916", "011_add_email_otps_table")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
