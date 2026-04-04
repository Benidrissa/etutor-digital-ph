"""Add credit system tables: credit_accounts, credit_transactions, credit_packages.

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
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_credit_accounts_user_id UNIQUE (user_id)
        )
        """
    )

    op.execute("CREATE INDEX IF NOT EXISTS ix_credit_accounts_user_id ON credit_accounts (user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_transactions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            account_id UUID NOT NULL REFERENCES credit_accounts(id) ON DELETE CASCADE,
            type transactiontype NOT NULL,
            amount BIGINT NOT NULL,
            balance_after BIGINT NOT NULL,
            reference_id UUID,
            reference_type VARCHAR(64),
            description TEXT NOT NULL,
            metadata_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credit_transactions_account_id ON credit_transactions (account_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credit_transactions_created_at ON credit_transactions (created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_credit_transactions_account_created ON credit_transactions (account_id, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS credit_packages (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name_fr VARCHAR(255) NOT NULL,
            name_en VARCHAR(255) NOT NULL,
            credits BIGINT NOT NULL,
            price_xof BIGINT NOT NULL,
            price_usd NUMERIC(10, 2) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    op.execute(
        """
        INSERT INTO credit_packages (id, name_fr, name_en, credits, price_xof, price_usd, is_active, sort_order)
        VALUES
            (gen_random_uuid(), 'Essai gratuit', 'Free trial', 100, 0, 0.00, true, 0),
            (gen_random_uuid(), 'Starter', 'Starter', 500, 2500, 5.00, true, 1),
            (gen_random_uuid(), 'Pro', 'Pro', 1500, 6500, 13.00, true, 2),
            (gen_random_uuid(), 'Expert', 'Expert', 5000, 18000, 36.00, true, 3)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS credit_transactions")
    op.execute("DROP TABLE IF EXISTS credit_accounts")
    op.execute("DROP TABLE IF EXISTS credit_packages")
    op.execute("DROP TYPE IF EXISTS transactiontype")
