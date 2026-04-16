"""Create question bank tables: question_banks, bank_questions, bank_tests, test_attempts.

Revision ID: 067
Revises: 066
Create Date: 2026-04-16

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE TYPE banktype AS ENUM ('exam', 'training', 'mixed')")
    op.execute("CREATE TYPE testmode AS ENUM ('exam', 'training', 'review')")

    op.create_table(
        "question_banks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "bank_type",
            sa.Enum("exam", "training", "mixed", name="banktype", create_type=False),
            nullable=False,
            server_default="mixed",
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qbanks_org_id", "question_banks", ["organization_id"])
    op.create_index("ix_qbanks_is_active", "question_banks", ["is_active"])

    op.create_table(
        "bank_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bank_id", sa.Uuid(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", JSONB, nullable=False),
        sa.Column("correct_answer", sa.Integer(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("difficulty", sa.String(20), server_default="medium", nullable=False),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bank_id"],
            ["question_banks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bquestions_bank_id", "bank_questions", ["bank_id"])
    op.create_index("ix_bquestions_category", "bank_questions", ["category"])
    op.create_index("ix_bquestions_is_active", "bank_questions", ["is_active"])

    op.create_table(
        "bank_tests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("bank_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "mode",
            sa.Enum("exam", "training", "review", name="testmode", create_type=False),
            nullable=False,
            server_default="exam",
        ),
        sa.Column("question_count", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("time_limit_minutes", sa.Integer(), nullable=True),
        sa.Column("passing_score", sa.Float(), nullable=False, server_default="70.0"),
        sa.Column("category_filter", sa.String(100), nullable=True),
        sa.Column("difficulty_filter", sa.String(20), nullable=True),
        sa.Column("shuffle_questions", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("show_answers", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["bank_id"],
            ["question_banks.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_btests_bank_id", "bank_tests", ["bank_id"])
    op.create_index("ix_btests_is_active", "bank_tests", ["is_active"])

    op.create_table(
        "test_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("answers", JSONB, nullable=False, server_default="'{}'"),
        sa.Column("question_ids", JSONB, nullable=False, server_default="'[]'"),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("category_breakdown", JSONB, nullable=False, server_default="'{}'"),
        sa.Column("time_taken_sec", sa.Integer(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["test_id"],
            ["bank_tests.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tattempts_test_id", "test_attempts", ["test_id"])
    op.create_index("ix_tattempts_user_id", "test_attempts", ["user_id"])
    op.create_index("ix_tattempts_test_user", "test_attempts", ["test_id", "user_id"])


def downgrade() -> None:
    op.drop_index("ix_tattempts_test_user", "test_attempts")
    op.drop_index("ix_tattempts_user_id", "test_attempts")
    op.drop_index("ix_tattempts_test_id", "test_attempts")
    op.drop_table("test_attempts")

    op.drop_index("ix_btests_is_active", "bank_tests")
    op.drop_index("ix_btests_bank_id", "bank_tests")
    op.drop_table("bank_tests")

    op.drop_index("ix_bquestions_is_active", "bank_questions")
    op.drop_index("ix_bquestions_category", "bank_questions")
    op.drop_index("ix_bquestions_bank_id", "bank_questions")
    op.drop_table("bank_questions")

    op.drop_index("ix_qbanks_is_active", "question_banks")
    op.drop_index("ix_qbanks_org_id", "question_banks")
    op.drop_table("question_banks")

    op.execute("DROP TYPE testmode")
    op.execute("DROP TYPE banktype")
