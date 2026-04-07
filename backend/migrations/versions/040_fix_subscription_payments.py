"""Fix subscription payments: add message_credits to subscriptions, make user_id nullable in payments.

Revision ID: 040
Revises: 039
Create Date: 2026-04-07

"""

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE subscriptions
        ADD COLUMN IF NOT EXISTS message_credits INTEGER NOT NULL DEFAULT 0
        """
    )

    op.execute(
        """
        ALTER TABLE subscription_payments
        ALTER COLUMN user_id DROP NOT NULL
        """
    )

    op.execute(
        """
        ALTER TABLE subscription_payments
        DROP CONSTRAINT IF EXISTS subscription_payments_user_id_fkey
        """
    )
    op.execute(
        """
        ALTER TABLE subscription_payments
        ADD CONSTRAINT subscription_payments_user_id_fkey
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE subscription_payments
        ALTER COLUMN user_id SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE subscriptions
        DROP COLUMN IF EXISTS message_credits
        """
    )
