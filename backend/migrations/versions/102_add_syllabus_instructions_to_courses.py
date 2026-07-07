"""Add syllabus_instructions column to courses

Admin-provided free-text guidance for AI syllabus generation (#2572).
Injected into the generation prompt alongside objectives; persisted so the
Celery task and regenerate paths read it from the course row.

Revision ID: 102_add_syllabus_instructions_to_courses
Revises: 101_add_image_overlay_text
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "102_add_syllabus_instructions_to_courses"
down_revision: str | None = "101_add_image_overlay_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("courses", sa.Column("syllabus_instructions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("courses", "syllabus_instructions")
