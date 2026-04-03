"""Add learner_memory table with JSONB fields for persistent learner preferences

Revision ID: 013_add_learner_memory_table
Revises: 012_invalidate_m01_m03_cached_lessons
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "013_add_learner_memory_table"
down_revision: str | None = "012_invalidate_m01_m03_cached_lessons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learner_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "difficulty_domains",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "preferred_explanation_style",
            sa.String(100),
            nullable=True,
        ),
        sa.Column(
            "preferred_country_examples",
            postgresql.ARRAY(sa.String()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "recurring_questions",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "declared_goals",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "learning_insights",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_learner_memory_user_id"),
    )
    op.create_index("ix_learner_memory_user_id", "learner_memory", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_learner_memory_user_id", table_name="learner_memory")
    op.drop_table("learner_memory")
