"""add_summative_assessment_attempts_table

Revision ID: 09a53bdc050e
Revises: 007_add_totp_mfa_auth_tables
Create Date: 2026-03-31 03:27:11.013972
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "09a53bdc050e"
down_revision: str | None = "007_add_totp_mfa_auth_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create summative_assessment_attempts table
    op.create_table(
        "summative_assessment_attempts",
        sa.Column("id", sa.UUID(), nullable=False, default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("module_id", sa.UUID(), nullable=False),
        sa.Column("assessment_id", sa.UUID(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("time_taken_sec", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("domain_breakdown", sa.JSON(), nullable=False),
        sa.Column("module_unlocked", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("can_retry_at", sa.DateTime(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["assessment_id"], ["generated_content.id"]),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # Add indexes for performance
    op.create_index(
        "ix_summative_assessment_attempts_user_id", "summative_assessment_attempts", ["user_id"]
    )
    op.create_index(
        "ix_summative_assessment_attempts_module_id", "summative_assessment_attempts", ["module_id"]
    )
    op.create_index(
        "ix_summative_assessment_attempts_assessment_id",
        "summative_assessment_attempts",
        ["assessment_id"],
    )
    op.create_index(
        "ix_summative_assessment_attempts_user_module",
        "summative_assessment_attempts",
        ["user_id", "module_id"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_summative_assessment_attempts_user_module", "summative_assessment_attempts")
    op.drop_index("ix_summative_assessment_attempts_assessment_id", "summative_assessment_attempts")
    op.drop_index("ix_summative_assessment_attempts_module_id", "summative_assessment_attempts")
    op.drop_index("ix_summative_assessment_attempts_user_id", "summative_assessment_attempts")

    # Drop table
    op.drop_table("summative_assessment_attempts")
