"""add_placement_test_attempts_table

Revision ID: 010_add_placement_test_attempts_table
Revises: 09a53bdc050e
Create Date: 2026-03-31 03:49:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_add_placement_test_attempts_table"
down_revision: str | None = "09a53bdc050e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create placement_test_attempts table
    op.create_table(
        "placement_test_attempts",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("raw_score", sa.Float(), nullable=False),
        sa.Column("adjusted_score", sa.Float(), nullable=False),
        sa.Column("assigned_level", sa.Integer(), nullable=False),
        sa.Column("time_taken_sec", sa.Integer(), nullable=False),
        sa.Column("domain_scores", sa.JSON(), nullable=False),
        sa.Column("user_context", sa.JSON(), nullable=False),
        sa.Column("competency_areas", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("can_retake_after", sa.DateTime(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index("ix_placement_test_attempts_user_id", "placement_test_attempts", ["user_id"])
    op.create_index(
        "ix_placement_test_attempts_attempted_at", "placement_test_attempts", ["attempted_at"]
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_placement_test_attempts_attempted_at", "placement_test_attempts")
    op.drop_index("ix_placement_test_attempts_user_id", "placement_test_attempts")

    # Drop table
    op.drop_table("placement_test_attempts")
