"""Add lesson_readings table

Revision ID: 005_lesson_readings_table
Revises: 004_pgvector_document_chunks
Create Date: 2026-03-30 21:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "005_lesson_readings_table"
down_revision: str | None = "004_pgvector_document_chunks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create lesson_readings table
    op.create_table(
        "lesson_readings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lesson_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("time_spent_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completion_percentage", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("read_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["lesson_id"],
            ["generated_content.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_lesson_readings_user_id"), "lesson_readings", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_lesson_readings_lesson_id"), "lesson_readings", ["lesson_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_lesson_readings_lesson_id"), table_name="lesson_readings")
    op.drop_index(op.f("ix_lesson_readings_user_id"), table_name="lesson_readings")
    op.drop_table("lesson_readings")
