"""Add compacted_context, compacted_at, message_count to tutor_conversations

Revision ID: 014_add_compacted_context_to_conversations
Revises: 013_add_learner_memory_table
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "014_add_compacted_context_to_conversations"
down_revision: str | None = "013_add_learner_memory_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tutor_conversations",
        sa.Column("compacted_context", sa.Text(), nullable=True),
    )
    op.add_column(
        "tutor_conversations",
        sa.Column("compacted_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tutor_conversations",
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("tutor_conversations", "message_count")
    op.drop_column("tutor_conversations", "compacted_at")
    op.drop_column("tutor_conversations", "compacted_context")
