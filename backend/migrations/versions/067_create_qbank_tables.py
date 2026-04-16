"""Create question bank tables.

Revision ID: 067
Revises: 066
Create Date: 2026-04-16

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_banks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pass_score", sa.Float(), nullable=False, server_default="70.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_question_banks_organization_id", "question_banks", ["organization_id"])

    op.create_table(
        "qbank_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "bank_id",
            sa.Uuid(),
            sa.ForeignKey("question_banks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("stem", sa.Text(), nullable=False),
        sa.Column("options", JSON(), nullable=False),
        sa.Column("correct_option", sa.String(10), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("difficulty", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_qbank_questions_bank_id", "qbank_questions", ["bank_id"])
    op.create_index("ix_qbank_questions_category", "qbank_questions", ["category"])

    op.create_table(
        "qbank_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "bank_id",
            sa.Uuid(),
            sa.ForeignKey("question_banks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("answers", JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("time_taken_sec", sa.Integer(), nullable=True),
        sa.Column("category_breakdown", JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_qbank_attempts_bank_id", "qbank_attempts", ["bank_id"])
    op.create_index("ix_qbank_attempts_user_id", "qbank_attempts", ["user_id"])
    op.create_index(
        "ix_qbank_attempts_bank_user", "qbank_attempts", ["bank_id", "user_id"]
    )
    op.create_index("ix_qbank_attempts_attempted_at", "qbank_attempts", ["attempted_at"])


def downgrade() -> None:
    op.drop_index("ix_qbank_attempts_attempted_at", "qbank_attempts")
    op.drop_index("ix_qbank_attempts_bank_user", "qbank_attempts")
    op.drop_index("ix_qbank_attempts_user_id", "qbank_attempts")
    op.drop_index("ix_qbank_attempts_bank_id", "qbank_attempts")
    op.drop_table("qbank_attempts")

    op.drop_index("ix_qbank_questions_category", "qbank_questions")
    op.drop_index("ix_qbank_questions_bank_id", "qbank_questions")
    op.drop_table("qbank_questions")

    op.drop_index("ix_question_banks_organization_id", "question_banks")
    op.drop_table("question_banks")
