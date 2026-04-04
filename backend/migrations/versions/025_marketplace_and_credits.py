"""Marketplace tables + credit system tables.

Adds is_marketplace and expert_id to courses, payment_transaction_id to
user_course_enrollment, creates course_prices, course_reviews, credit_accounts,
transactions, and credit_packages tables.

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
    # --- Credit system (must come first — transactions table is FK'd below) ---
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

    # --- Marketplace columns on courses ---
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_marketplace BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS expert_id UUID REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_courses_expert_id ON courses (expert_id)")
    op.execute("UPDATE courses SET is_marketplace = false WHERE is_marketplace IS NULL")

    # --- payment_transaction_id on enrollment ---
    op.execute(
        """
        ALTER TABLE user_course_enrollment
        ADD COLUMN IF NOT EXISTS payment_transaction_id UUID
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enrollment_payment_tx ON user_course_enrollment (payment_transaction_id)"
    )

    # --- course_prices ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_prices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            course_id UUID NOT NULL UNIQUE REFERENCES courses(id) ON DELETE CASCADE,
            price_credits BIGINT NOT NULL DEFAULT 0,
            is_free BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_prices_course_id ON course_prices (course_id)")

    # --- course_reviews ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_course_reviews_course_user UNIQUE (course_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_reviews_course_id ON course_reviews (course_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_reviews_user_id ON course_reviews (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS course_reviews")
    op.execute("DROP TABLE IF EXISTS course_prices")

    op.execute("DROP INDEX IF EXISTS ix_enrollment_payment_tx")
    op.execute(
        "ALTER TABLE user_course_enrollment DROP COLUMN IF EXISTS payment_transaction_id"
    )

    op.execute("DROP INDEX IF EXISTS ix_courses_expert_id")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS expert_id")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS is_marketplace")

    op.execute("DROP TABLE IF EXISTS credit_packages")
    op.execute("DROP TABLE IF EXISTS transactions")
    op.execute("DROP TABLE IF EXISTS credit_accounts")
    op.execute("DROP TYPE IF EXISTS transactiontype")
