"""Create credit system tables: credit_accounts, transactions, credit_packages.

Implements the unified credit economy for Phase 2 billing.

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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS credit_accounts")
    op.execute("DROP TABLE IF EXISTS credit_packages")
    op.execute("DROP TYPE IF EXISTS transactiontype")
