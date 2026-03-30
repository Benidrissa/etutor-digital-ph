"""Initial database schema — all 7 tables from SRS Section 9.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-03-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("preferred_language", sa.String(2), server_default="fr"),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("professional_role", sa.String(), nullable=True),
        sa.Column("current_level", sa.Integer(), server_default="1"),
        sa.Column("streak_days", sa.Integer(), server_default="0"),
        sa.Column("last_active", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("idx_users_last_active", "users", ["last_active"])

    # --- modules ---
    op.create_table(
        "modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("module_number", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("estimated_hours", sa.Integer(), server_default="20"),
        sa.Column("bloom_level", sa.String(), nullable=True),
        sa.Column(
            "prereq_modules",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
        ),
        sa.Column("books_sources", sa.JSON(), nullable=True),
    )
    op.create_index("ix_modules_module_number", "modules", ["module_number"], unique=True)
    op.create_index("idx_modules_level", "modules", ["level"])

    # --- user_module_progress ---
    op.create_table(
        "user_module_progress",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(), server_default="locked"),
        sa.Column("completion_pct", sa.Float(), server_default="0.0"),
        sa.Column("quiz_score_avg", sa.Float(), nullable=True),
        sa.Column("time_spent_minutes", sa.Integer(), server_default="0"),
        sa.Column("last_accessed", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("user_id", "module_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"]),
    )
    op.create_index("idx_progress_user_id", "user_module_progress", ["user_id"])
    op.create_index("idx_progress_module_id", "user_module_progress", ["module_id"])
    op.create_index("idx_progress_status", "user_module_progress", ["status"])

    # --- generated_content ---
    op.create_table(
        "generated_content",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("language", sa.String(2), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("sources_cited", sa.JSON(), nullable=True),
        sa.Column("country_context", sa.String(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("validated", sa.Boolean(), server_default="false"),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"]),
    )
    op.create_index("idx_content_module_id", "generated_content", ["module_id"])
    op.create_index("idx_content_type", "generated_content", ["content_type"])
    op.create_index("idx_content_language", "generated_content", ["language"])

    # --- quiz_attempts ---
    op.create_table(
        "quiz_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quiz_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("time_taken_sec", sa.Integer(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["quiz_id"], ["generated_content.id"]),
    )
    op.create_index("idx_quiz_user_id", "quiz_attempts", ["user_id"])
    op.create_index("idx_quiz_quiz_id", "quiz_attempts", ["quiz_id"])

    # --- flashcard_reviews ---
    op.create_table(
        "flashcard_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("card_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(), nullable=False),
        sa.Column("next_review", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stability", sa.Float(), server_default="1.0"),
        sa.Column("difficulty", sa.Float(), server_default="5.0"),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["card_id"], ["generated_content.id"]),
    )
    op.create_index("idx_flashcard_user_id", "flashcard_reviews", ["user_id"])
    op.create_index("idx_flashcard_card_id", "flashcard_reviews", ["card_id"])
    op.create_index("idx_flashcard_next_review", "flashcard_reviews", ["next_review"])

    # --- tutor_conversations ---
    op.create_table(
        "tutor_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["module_id"], ["modules.id"]),
    )
    op.create_index("idx_conversation_user_id", "tutor_conversations", ["user_id"])


def downgrade() -> None:
    op.drop_table("tutor_conversations")
    op.drop_table("flashcard_reviews")
    op.drop_table("quiz_attempts")
    op.drop_table("generated_content")
    op.drop_table("user_module_progress")
    op.drop_table("modules")
    op.drop_table("users")
