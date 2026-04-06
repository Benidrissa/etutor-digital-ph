"""Add password auth columns and password_reset_tokens table.

Revision ID: 037
Revises: 036
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "failed_password_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("password_locked_until", sa.DateTime(timezone=True), nullable=True),
    )

    op.alter_column("users", "email", nullable=True)

    op.drop_index("ix_users_email", table_name="users")
    op.execute("CREATE UNIQUE INDEX ix_users_email_unique ON users(email) WHERE email IS NOT NULL")
    op.execute(
        "CREATE UNIQUE INDEX ix_users_phone_unique ON users(phone_number) WHERE phone_number IS NOT NULL"
    )

    op.create_check_constraint(
        "ck_users_email_or_phone",
        "users",
        "email IS NOT NULL OR phone_number IS NOT NULL",
    )

    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(128), unique=True, nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens")

    op.drop_constraint("ck_users_email_or_phone", "users", type_="check")

    op.execute("DROP INDEX IF EXISTS ix_users_phone_unique")
    op.execute("DROP INDEX IF EXISTS ix_users_email_unique")
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.alter_column("users", "email", nullable=False)

    op.drop_column("users", "password_locked_until")
    op.drop_column("users", "failed_password_attempts")
    op.drop_column("users", "password_hash")
