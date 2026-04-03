"""Extend email_otps.code column to store SHA-256 hashes.

Revision ID: 019_hash_email_otp_codes
Revises: 018_add_totp_brute_force_protection
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "019_hash_email_otp_codes"
down_revision: str | None = "018_add_totp_brute_force_protection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "email_otps",
        "code",
        existing_type=sa.String(6),
        type_=sa.String(64),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "email_otps",
        "code",
        existing_type=sa.String(64),
        type_=sa.String(6),
        existing_nullable=False,
    )
