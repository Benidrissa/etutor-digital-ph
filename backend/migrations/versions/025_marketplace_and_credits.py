"""Add api_usage_logs table for API usage and generation cost tracking.

Tracks every AI API call with token counts and credit costs to enable
per-user billing, cost analytics, and platform cost visibility.

Revision ID: 025_marketplace_and_credits
Revises: 024_add_course_taxonomy
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025_marketplace_and_credits"
down_revision: str | None = "024_add_course_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE usagecategory AS ENUM ('user', 'expert', 'system');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE requesttype AS ENUM (
                'lesson', 'quiz', 'flashcard', 'case_study',
                'tutor_chat', 'embedding', 'rag_indexing', 'course_structure'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS api_usage_logs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            course_id   UUID REFERENCES courses(id) ON DELETE SET NULL,
            module_id   UUID REFERENCES modules(id) ON DELETE SET NULL,
            content_id  UUID REFERENCES generated_content(id) ON DELETE SET NULL,
            usage_category  usagecategory NOT NULL,
            request_type    requesttype   NOT NULL,
            api_provider    VARCHAR       NOT NULL,
            model_name      VARCHAR       NOT NULL,
            input_tokens    INTEGER       NOT NULL,
            output_tokens   INTEGER       NOT NULL,
            cost_credits    BIGINT        NOT NULL,
            cost_usd        NUMERIC(10,6) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_usage_logs_user_id ON api_usage_logs (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_usage_logs_course_id ON api_usage_logs (course_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_api_usage_logs_created_at ON api_usage_logs (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_api_usage_logs_created_at")
    op.execute("DROP INDEX IF EXISTS ix_api_usage_logs_course_id")
    op.execute("DROP INDEX IF EXISTS ix_api_usage_logs_user_id")
    op.execute("DROP TABLE IF EXISTS api_usage_logs")
    op.execute("DROP TYPE IF EXISTS requesttype")
    op.execute("DROP TYPE IF EXISTS usagecategory")
