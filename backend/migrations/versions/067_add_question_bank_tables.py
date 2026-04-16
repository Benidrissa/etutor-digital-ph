"""Add question bank tables for image-based MCQ system.

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
    # Create enum types via raw SQL with IF NOT EXISTS to avoid conflicts
    # with SQLAlchemy model-level enum auto-creation in asyncpg.
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE questionbanktype AS ENUM (
                'driving', 'exam_prep', 'psychotechnic', 'general_culture'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE questionbankstatus AS ENUM ('draft', 'published', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE questiondifficulty AS ENUM ('easy', 'medium', 'hard');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE testmode AS ENUM ('exam', 'training', 'review');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE qbankaudiostatus AS ENUM (
                'pending', 'generating', 'ready', 'failed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    op.create_table(
        "question_banks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.Uuid(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("bank_type", sa.VARCHAR(50), nullable=False),
        sa.Column("language", sa.String(5), server_default="fr", nullable=False),
        sa.Column("time_per_question_sec", sa.Integer(), server_default="25", nullable=False),
        sa.Column("passing_score", sa.Float(), server_default="80.0", nullable=False),
        sa.Column("status", sa.VARCHAR(50), server_default="draft", nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Cast columns to their enum types
    op.execute(
        "ALTER TABLE question_banks ALTER COLUMN bank_type TYPE questionbanktype"
        " USING bank_type::questionbanktype"
    )
    op.execute(
        "ALTER TABLE question_banks ALTER COLUMN status TYPE questionbankstatus"
        " USING status::questionbankstatus"
    )

    op.create_table(
        "qbank_questions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "question_bank_id",
            sa.Uuid(),
            sa.ForeignKey("question_banks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("image_storage_key", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("options", JSON(), nullable=False),
        sa.Column("correct_answer_indices", JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_pdf_name", sa.String(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("difficulty", sa.VARCHAR(50), server_default="medium", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute(
        "ALTER TABLE qbank_questions ALTER COLUMN difficulty TYPE questiondifficulty"
        " USING difficulty::questiondifficulty"
    )

    op.create_table(
        "qbank_question_audio",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "question_id",
            sa.Uuid(),
            sa.ForeignKey("qbank_questions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("storage_url", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.VARCHAR(50), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("question_id", "language", name="uq_qbank_question_audio_lang"),
    )
    op.execute(
        "ALTER TABLE qbank_question_audio ALTER COLUMN status TYPE qbankaudiostatus"
        " USING status::qbankaudiostatus"
    )

    op.create_table(
        "qbank_tests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "question_bank_id",
            sa.Uuid(),
            sa.ForeignKey("question_banks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("mode", sa.VARCHAR(50), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=True),
        sa.Column("shuffle_questions", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("time_per_question_sec", sa.Integer(), nullable=True),
        sa.Column("show_feedback", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("filter_categories", JSON(), nullable=True),
        sa.Column("filter_failed_only", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE qbank_tests ALTER COLUMN mode TYPE testmode USING mode::testmode")

    op.create_table(
        "qbank_test_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "test_id",
            sa.Uuid(),
            sa.ForeignKey("qbank_tests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("answers", JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("total_questions", sa.Integer(), nullable=False),
        sa.Column("correct_answers", sa.Integer(), nullable=False),
        sa.Column("time_taken_sec", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("category_breakdown", JSON(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
    )


def downgrade() -> None:
    op.drop_table("qbank_test_attempts")
    op.drop_table("qbank_tests")
    op.drop_table("qbank_question_audio")
    op.drop_table("qbank_questions")
    op.drop_table("question_banks")
    op.execute("DROP TYPE IF EXISTS qbankaudiostatus")
    op.execute("DROP TYPE IF EXISTS testmode")
    op.execute("DROP TYPE IF EXISTS questiondifficulty")
    op.execute("DROP TYPE IF EXISTS questionbankstatus")
    op.execute("DROP TYPE IF EXISTS questionbanktype")
