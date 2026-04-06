"""Add relay_devices and inbound_sms tables for SMS relay payment system.

Revision ID: 036
Revises: 035
Create Date: 2026-04-06

"""

import sqlalchemy as sa
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type
    op.execute(
        "CREATE TYPE smsprocessingstatus AS ENUM "
        "('pending','parsed','payment_processed',"
        "'parse_failed','duplicate','ignored')"
    )

    # relay_devices table
    op.create_table(
        "relay_devices",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "device_id",
            sa.String(100),
            unique=True,
            nullable=False,
        ),
        sa.Column("battery", sa.Integer(), nullable=True),
        sa.Column("charging", sa.Boolean(), nullable=True),
        sa.Column("signal", sa.Integer(), nullable=True),
        sa.Column("pending", sa.Integer(), nullable=True),
        sa.Column("failed", sa.Integer(), nullable=True),
        sa.Column(
            "last_sms_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "app_version", sa.String(20), nullable=True
        ),
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # inbound_sms table
    op.create_table(
        "inbound_sms",
        sa.Column(
            "id",
            sa.UUID(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "sms_id",
            sa.String(100),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "device_id",
            sa.String(100),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "sender", sa.String(50), nullable=False
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "sms_received_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "app_version", sa.String(20), nullable=True
        ),
        sa.Column(
            "processing_status",
            sa.Enum(
                "pending",
                "parsed",
                "payment_processed",
                "parse_failed",
                "duplicate",
                "ignored",
                name="smsprocessingstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "parsed_amount", sa.Integer(), nullable=True
        ),
        sa.Column(
            "parsed_phone", sa.String(20), nullable=True
        ),
        sa.Column(
            "parsed_reference",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "parsed_provider",
            sa.String(50),
            nullable=True,
        ),
        sa.Column(
            "error_message", sa.Text(), nullable=True
        ),
        sa.Column(
            "payment_id",
            sa.UUID(),
            sa.ForeignKey(
                "subscription_payments.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Additional indexes
    op.create_index(
        "ix_inbound_sms_status",
        "inbound_sms",
        ["processing_status"],
    )
    op.create_index(
        "ix_inbound_sms_created",
        "inbound_sms",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("inbound_sms")
    op.drop_table("relay_devices")
    op.execute("DROP TYPE IF EXISTS smsprocessingstatus")
