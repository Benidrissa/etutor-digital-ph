"""Add CASCADE to 9 FKs for unenroll data deletion; add delete_course to adminaction enum.

Revision ID: 052
Revises: 051
Create Date: 2026-04-09

"""

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Add delete_course to adminaction enum ---
    op.execute("ALTER TYPE adminaction ADD VALUE IF NOT EXISTS 'delete_course'")

    # --- generated_content.module_id -> modules.id CASCADE ---
    op.drop_constraint("generated_content_module_id_fkey", "generated_content", type_="foreignkey")
    op.create_foreign_key(
        "generated_content_module_id_fkey",
        "generated_content",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- user_module_progress.module_id -> modules.id CASCADE ---
    op.drop_constraint(
        "user_module_progress_module_id_fkey", "user_module_progress", type_="foreignkey"
    )
    op.create_foreign_key(
        "user_module_progress_module_id_fkey",
        "user_module_progress",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- summative_assessment_attempts.module_id -> modules.id CASCADE ---
    op.drop_constraint(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- summative_assessment_attempts.assessment_id -> generated_content.id CASCADE ---
    op.drop_constraint(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        "generated_content",
        ["assessment_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- tutor_conversations.module_id -> modules.id CASCADE ---
    op.drop_constraint(
        "tutor_conversations_module_id_fkey", "tutor_conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "tutor_conversations_module_id_fkey",
        "tutor_conversations",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- module_units.module_id -> modules.id CASCADE ---
    op.drop_constraint("module_units_module_id_fkey", "module_units", type_="foreignkey")
    op.create_foreign_key(
        "module_units_module_id_fkey",
        "module_units",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- quiz_attempts.quiz_id -> generated_content.id CASCADE ---
    op.drop_constraint("quiz_attempts_quiz_id_fkey", "quiz_attempts", type_="foreignkey")
    op.create_foreign_key(
        "quiz_attempts_quiz_id_fkey",
        "quiz_attempts",
        "generated_content",
        ["quiz_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- flashcard_reviews.card_id -> generated_content.id CASCADE ---
    op.drop_constraint("flashcard_reviews_card_id_fkey", "flashcard_reviews", type_="foreignkey")
    op.create_foreign_key(
        "flashcard_reviews_card_id_fkey",
        "flashcard_reviews",
        "generated_content",
        ["card_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # --- lesson_readings.lesson_id -> generated_content.id CASCADE ---
    op.drop_constraint("lesson_readings_lesson_id_fkey", "lesson_readings", type_="foreignkey")
    op.create_foreign_key(
        "lesson_readings_lesson_id_fkey",
        "lesson_readings",
        "generated_content",
        ["lesson_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Restore lesson_readings.lesson_id (no CASCADE)
    op.drop_constraint("lesson_readings_lesson_id_fkey", "lesson_readings", type_="foreignkey")
    op.create_foreign_key(
        "lesson_readings_lesson_id_fkey",
        "lesson_readings",
        "generated_content",
        ["lesson_id"],
        ["id"],
    )

    # Restore flashcard_reviews.card_id (no CASCADE)
    op.drop_constraint("flashcard_reviews_card_id_fkey", "flashcard_reviews", type_="foreignkey")
    op.create_foreign_key(
        "flashcard_reviews_card_id_fkey",
        "flashcard_reviews",
        "generated_content",
        ["card_id"],
        ["id"],
    )

    # Restore quiz_attempts.quiz_id (no CASCADE)
    op.drop_constraint("quiz_attempts_quiz_id_fkey", "quiz_attempts", type_="foreignkey")
    op.create_foreign_key(
        "quiz_attempts_quiz_id_fkey",
        "quiz_attempts",
        "generated_content",
        ["quiz_id"],
        ["id"],
    )

    # Restore module_units.module_id (no CASCADE)
    op.drop_constraint("module_units_module_id_fkey", "module_units", type_="foreignkey")
    op.create_foreign_key(
        "module_units_module_id_fkey",
        "module_units",
        "modules",
        ["module_id"],
        ["id"],
    )

    # Restore tutor_conversations.module_id (no CASCADE)
    op.drop_constraint(
        "tutor_conversations_module_id_fkey", "tutor_conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "tutor_conversations_module_id_fkey",
        "tutor_conversations",
        "modules",
        ["module_id"],
        ["id"],
    )

    # Restore summative_assessment_attempts.assessment_id (no CASCADE)
    op.drop_constraint(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_assessment_id_fkey",
        "summative_assessment_attempts",
        "generated_content",
        ["assessment_id"],
        ["id"],
    )

    # Restore summative_assessment_attempts.module_id (no CASCADE)
    op.drop_constraint(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "summative_assessment_attempts_module_id_fkey",
        "summative_assessment_attempts",
        "modules",
        ["module_id"],
        ["id"],
    )

    # Restore user_module_progress.module_id (no CASCADE)
    op.drop_constraint(
        "user_module_progress_module_id_fkey", "user_module_progress", type_="foreignkey"
    )
    op.create_foreign_key(
        "user_module_progress_module_id_fkey",
        "user_module_progress",
        "modules",
        ["module_id"],
        ["id"],
    )

    # Restore generated_content.module_id (no CASCADE)
    op.drop_constraint("generated_content_module_id_fkey", "generated_content", type_="foreignkey")
    op.create_foreign_key(
        "generated_content_module_id_fkey",
        "generated_content",
        "modules",
        ["module_id"],
        ["id"],
    )

    # Note: Cannot remove enum values in PostgreSQL without recreating the type.
    # The delete_course value is left in the enum during downgrade.
