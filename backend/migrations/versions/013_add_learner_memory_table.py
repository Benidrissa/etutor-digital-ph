"""add learner_memory table

Revision ID: 013_add_learner_memory
Revises: 012_invalidate_m01_m03_cached_lessons
Create Date: 2026-04-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013_add_learner_memory"
down_revision: str | None = "012_invalidate_m01_m03_cached_lessons"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learner_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("preference_type", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_learner_memory_user_id", "learner_memory", ["user_id"])
    op.create_index(
        "ix_learner_memory_user_pref",
        "learner_memory",
        ["user_id", "preference_type"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_learner_memory_user_pref", table_name="learner_memory")
    op.drop_index("ix_learner_memory_user_id", table_name="learner_memory")
    op.drop_table("learner_memory")
