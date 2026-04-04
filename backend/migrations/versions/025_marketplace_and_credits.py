"""Credit system + API usage tracking tables.

Creates credit_accounts, transactions, credit_packages, and api_usage_logs.

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
    # --- Credit system enums and tables ---
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE transactiontype AS ENUM (
                'credit_purchase',
                'content_access',
                'tutor_usage',
                'offline_download',
                'course_purchase',
                'course_earning',
                'commission',
                'expert_activation',
                'generation_cost',
                'payout',
                'refund',
                'free_trial'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_accounts (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            balance BIGINT NOT NULL DEFAULT 0,
            total_purchased BIGINT NOT NULL DEFAULT 0,
            total_spent BIGINT NOT NULL DEFAULT 0,
            total_earned BIGINT NOT NULL DEFAULT 0,
            total_withdrawn BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_credit_accounts_user_id UNIQUE (user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_accounts_user_id ON credit_accounts (user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id UUID NOT NULL REFERENCES credit_accounts(id) ON DELETE CASCADE,
            type transactiontype NOT NULL,
            amount BIGINT NOT NULL,
            balance_after BIGINT NOT NULL,
            reference_id UUID,
            reference_type VARCHAR(50),
            description TEXT NOT NULL,
            metadata_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_transactions_account_id ON transactions (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_transactions_created_at ON transactions (created_at)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transactions_account_id_created_at "
        "ON transactions (account_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_packages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name_fr VARCHAR NOT NULL,
            name_en VARCHAR NOT NULL,
            credits BIGINT NOT NULL,
            price_xof BIGINT NOT NULL,
            price_usd NUMERIC(10, 2) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT true,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    # --- API usage tracking ---
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

    op.execute("DROP TABLE IF EXISTS credit_packages")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS credit_accounts")
    op.execute("DROP TYPE IF EXISTS transactiontype")
