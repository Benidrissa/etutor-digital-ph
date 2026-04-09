"""add activation_codes, activation_code_redemptions, course visibility and pricing columns

Revision ID: 052
Revises: 051
Create Date: 2026-04-09

"""

import sqlalchemy as sa
from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column("visibility", sa.String(10), nullable=False, server_default="public"),
    )
    op.add_column(
        "courses",
        sa.Column("price_credits", sa.BIGINT(), nullable=False, server_default="0"),
    )

    op.create_table(
        "activation_codes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("times_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_activation_codes_code"),
    )
    op.create_index("ix_activation_codes_code", "activation_codes", ["code"])
    op.create_index("ix_activation_codes_course_id", "activation_codes", ["course_id"])

    op.create_table(
        "activation_code_redemptions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "redeemed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("activated_by", sa.UUID(), nullable=True),
        sa.Column("credit_transaction_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["code_id"], ["activation_codes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["activated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["credit_transaction_id"], ["transactions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_id", "user_id", name="uq_activation_code_redemptions_code_user"),
    )
    op.create_index(
        "ix_activation_code_redemptions_code_id", "activation_code_redemptions", ["code_id"]
    )
    op.create_index(
        "ix_activation_code_redemptions_user_id", "activation_code_redemptions", ["user_id"]
    )
    op.create_index(
        "ix_activation_code_redemptions_code_id_user_id",
        "activation_code_redemptions",
        ["code_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_activation_code_redemptions_code_id_user_id",
        table_name="activation_code_redemptions",
    )
    op.drop_index(
        "ix_activation_code_redemptions_user_id", table_name="activation_code_redemptions"
    )
    op.drop_index(
        "ix_activation_code_redemptions_code_id", table_name="activation_code_redemptions"
    )
    op.drop_table("activation_code_redemptions")
    op.drop_index("ix_activation_codes_course_id", table_name="activation_codes")
    op.drop_index("ix_activation_codes_code", table_name="activation_codes")
    op.drop_table("activation_codes")
    op.drop_column("courses", "price_credits")
    op.drop_column("courses", "visibility")
