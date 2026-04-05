"""Add phone_number to users; create subscriptions and subscription_payments tables.

Revision ID: 033
Revises: 032
Create Date: 2026-04-05

"""

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20)
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_phone_number ON users (phone_number)"
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE subscriptionstatus AS ENUM (
                'active',
                'expired',
                'cancelled',
                'pending_payment'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE paymenttype AS ENUM (
                'access',
                'messages'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE paymentstatus AS ENUM (
                'pending',
                'confirmed',
                'expired'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subscriptions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            phone_number VARCHAR(20) NOT NULL,
            status subscriptionstatus NOT NULL DEFAULT 'pending_payment',
            daily_message_limit INTEGER NOT NULL DEFAULT 20,
            expires_at TIMESTAMPTZ NOT NULL,
            activated_at TIMESTAMPTZ NOT NULL,
            pending_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_subscriptions_user_id UNIQUE (user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subscriptions_user_id ON subscriptions (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subscriptions_phone_number ON subscriptions (phone_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subscriptions_status ON subscriptions (status)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subscription_payments (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            phone_number VARCHAR(20) NOT NULL,
            amount_xof INTEGER NOT NULL,
            payment_type paymenttype NOT NULL,
            external_reference VARCHAR(255) NOT NULL,
            status paymentstatus NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_subscription_payments_external_reference UNIQUE (external_reference)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subscription_payments_user_id ON subscription_payments (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_subscription_payments_phone_number ON subscription_payments (phone_number)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS subscription_payments")
    op.execute("DROP TABLE IF EXISTS subscriptions")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS paymenttype")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
    op.execute("DROP INDEX IF EXISTS ix_users_phone_number")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS phone_number")
