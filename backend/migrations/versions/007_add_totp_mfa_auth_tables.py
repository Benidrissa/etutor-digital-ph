"""Add TOTP MFA auth tables

Revision ID: 001_add_totp_mfa_auth_tables
Revises:
Create Date: 2026-03-30 23:24:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007_add_totp_mfa_auth_tables"
down_revision: str | None = "006_detailed_m01_m03_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create totp_secrets table
    op.create_table(
        "totp_secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("secret", sa.String(32), nullable=False),
        sa.Column("backup_codes", sa.Text(), nullable=True),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_totp_secrets_user_id"), "totp_secrets", ["user_id"], unique=True)

    # Create refresh_tokens table
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_refresh_tokens_token_hash"), "refresh_tokens", ["token_hash"], unique=True
    )

    # Create magic_links table
    op.create_table(
        "magic_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_magic_links_user_id"), "magic_links", ["user_id"], unique=False)
    op.create_index(op.f("ix_magic_links_token_hash"), "magic_links", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_magic_links_token_hash"), table_name="magic_links")
    op.drop_index(op.f("ix_magic_links_user_id"), table_name="magic_links")
    op.drop_table("magic_links")

    op.drop_index(op.f("ix_refresh_tokens_token_hash"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index(op.f("ix_totp_secrets_user_id"), table_name="totp_secrets")
    op.drop_table("totp_secrets")
