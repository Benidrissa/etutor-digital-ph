"""Add phone_otps table for WhatsApp-based OTP verification.

Revision ID: 083
Revises: 082
Create Date: 2026-04-25

Mirrors the email_otps table (#011) but keyed on a phone number and tagged
with a delivery ``channel`` ("whatsapp" by default; future-proofing for SMS).
Forward-only with IF NOT EXISTS guards so partial-retry deploys are safe,
matching the 082 pattern.
"""

from alembic import op

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS phone_otps (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID REFERENCES users(id) ON DELETE CASCADE,
            phone_number VARCHAR(20) NOT NULL,
            code VARCHAR(64) NOT NULL,
            channel VARCHAR(16) NOT NULL DEFAULT 'whatsapp',
            purpose VARCHAR(20) NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            verified_at TIMESTAMPTZ,
            ip_address VARCHAR(45)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_phone_otps_user_id ON phone_otps (user_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_phone_otps_phone_number ON phone_otps (phone_number);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_phone_otps_phone_number;")
    op.execute("DROP INDEX IF EXISTS ix_phone_otps_user_id;")
    op.execute("DROP TABLE IF EXISTS phone_otps;")
