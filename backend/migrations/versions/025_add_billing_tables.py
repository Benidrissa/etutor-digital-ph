"""Add billing tables: credit_packages, credit_transactions, api_usage_logs.

Revision ID: 025_add_billing_tables
Revises: 024_add_course_taxonomy
Create Date: 2026-04-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025_add_billing_tables"
down_revision: str | None = "024_add_course_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_PACKAGES = [
    {
        "id": "10000000-0000-0000-0000-000000000001",
        "name_fr": "Débutant",
        "name_en": "Starter",
        "credits": 100,
        "price_xof": 2000,
        "price_usd": 3.00,
    },
    {
        "id": "10000000-0000-0000-0000-000000000002",
        "name_fr": "Essentiel",
        "name_en": "Essential",
        "credits": 500,
        "price_xof": 8000,
        "price_usd": 12.00,
    },
    {
        "id": "10000000-0000-0000-0000-000000000003",
        "name_fr": "Professionnel",
        "name_en": "Professional",
        "credits": 1500,
        "price_xof": 20000,
        "price_usd": 30.00,
    },
]


def upgrade() -> None:
    op.create_table(
        "credit_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name_fr", sa.String(200), nullable=False),
        sa.Column("name_en", sa.String(200), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("price_xof", sa.Integer(), nullable=False),
        sa.Column("price_usd", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )

    op.create_table(
        "credit_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["package_id"], ["credit_packages.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_credit_transactions_user_id", "credit_transactions", ["user_id"])
    op.create_index("ix_credit_transactions_created_at", "credit_transactions", ["created_at"])

    op.create_table(
        "api_usage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("usage_type", sa.String(100), nullable=False),
        sa.Column("credits_spent", sa.Integer(), server_default="0", nullable=False),
        sa.Column("metadata", postgresql.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_api_usage_logs_user_id", "api_usage_logs", ["user_id"])
    op.create_index("ix_api_usage_logs_created_at", "api_usage_logs", ["created_at"])

    op.execute(
        f"""
        INSERT INTO credit_packages (id, name_fr, name_en, credits, price_xof, price_usd)
        VALUES
            ('{DEFAULT_PACKAGES[0]["id"]}', '{DEFAULT_PACKAGES[0]["name_fr"]}',
             '{DEFAULT_PACKAGES[0]["name_en"]}', {DEFAULT_PACKAGES[0]["credits"]},
             {DEFAULT_PACKAGES[0]["price_xof"]}, {DEFAULT_PACKAGES[0]["price_usd"]}),
            ('{DEFAULT_PACKAGES[1]["id"]}', '{DEFAULT_PACKAGES[1]["name_fr"]}',
             '{DEFAULT_PACKAGES[1]["name_en"]}', {DEFAULT_PACKAGES[1]["credits"]},
             {DEFAULT_PACKAGES[1]["price_xof"]}, {DEFAULT_PACKAGES[1]["price_usd"]}),
            ('{DEFAULT_PACKAGES[2]["id"]}', '{DEFAULT_PACKAGES[2]["name_fr"]}',
             '{DEFAULT_PACKAGES[2]["name_en"]}', {DEFAULT_PACKAGES[2]["credits"]},
             {DEFAULT_PACKAGES[2]["price_xof"]}, {DEFAULT_PACKAGES[2]["price_usd"]})
        """
    )


def downgrade() -> None:
    op.drop_table("api_usage_logs")
    op.drop_table("credit_transactions")
    op.drop_table("credit_packages")
