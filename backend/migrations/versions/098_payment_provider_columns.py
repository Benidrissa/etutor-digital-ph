"""Add provider, currency, provider_reference to subscription_payments

Supports multi-provider payments (Orange Money / Wave / Paystack) via the
provider-API path (#2355). Plain string columns — no PG enum — so new rails
don't require a migration. Existing rows default to the historical SMS path.

Revision ID: 098_payment_provider_columns
Revises: 097_add_course_bundles
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "098_payment_provider_columns"
down_revision: str | None = "097_add_course_bundles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscription_payments",
        sa.Column(
            "provider",
            sa.String(length=20),
            nullable=False,
            server_default="orange_money",
        ),
    )
    op.add_column(
        "subscription_payments",
        sa.Column(
            "currency",
            sa.String(length=8),
            nullable=False,
            server_default="XOF",
        ),
    )
    op.add_column(
        "subscription_payments",
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscription_payments", "provider_reference")
    op.drop_column("subscription_payments", "currency")
    op.drop_column("subscription_payments", "provider")
