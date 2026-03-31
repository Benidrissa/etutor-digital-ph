"""Detailed seed data for M01-M03 — placeholder (detailed data added via API).

Revision ID: 006_detailed_m01_m03_seed
Revises: 005_lesson_readings_table
Create Date: 2026-03-30
"""

from collections.abc import Sequence

revision: str = "006_detailed_m01_m03_seed"
down_revision: str | None = "005_lesson_readings_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # M01-M03 basic data already seeded in migration 003.
    # Detailed metadata (units, learning objectives, book sources)
    # will be updated via the admin API or a data script.
    pass


def downgrade() -> None:
    pass
