"""Extend activation_codes + curricula with organization support.

Add organization_id and curriculum_id to activation_codes, make course_id nullable.
Add organization_id to curricula. Extend transactiontype enum with org values.

Revision ID: 061
Revises: 060
Create Date: 2026-04-13

"""

import sqlalchemy as sa
from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Extend transactiontype enum (must be outside transaction) ---
    op.execute("COMMIT")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'org_code_escrow'")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'org_code_refund'")
    op.execute("ALTER TYPE transactiontype ADD VALUE IF NOT EXISTS 'org_credit_purchase'")
    op.execute("BEGIN")

    # --- Extend activation_codes ---
    # Make course_id nullable (existing rows all have course_id set)
    op.alter_column("activation_codes", "course_id", existing_type=sa.Uuid(), nullable=True)

    # Add organization_id
    op.add_column("activation_codes", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_activation_codes_organization_id",
        "activation_codes",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_activation_codes_organization_id", "activation_codes", ["organization_id"])

    # Add curriculum_id
    op.add_column("activation_codes", sa.Column("curriculum_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_activation_codes_curriculum_id",
        "activation_codes",
        "curricula",
        ["curriculum_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_activation_codes_curriculum_id", "activation_codes", ["curriculum_id"])

    # CHECK constraints
    op.execute(
        "ALTER TABLE activation_codes ADD CONSTRAINT ck_activation_codes_course_or_curriculum "
        "CHECK ((course_id IS NOT NULL) OR (curriculum_id IS NOT NULL))"
    )
    op.execute(
        "ALTER TABLE activation_codes ADD CONSTRAINT ck_activation_codes_org_xor_expert "
        "CHECK ((organization_id IS NULL) OR (created_by IS NULL))"
    )
    op.execute(
        "ALTER TABLE activation_codes "
        "ADD CONSTRAINT ck_activation_codes_curriculum_requires_org "
        "CHECK ((curriculum_id IS NULL) OR (organization_id IS NOT NULL))"
    )

    # --- Extend curricula with organization_id ---
    op.add_column("curricula", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_curricula_organization_id",
        "curricula",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_curricula_organization_id", "curricula", ["organization_id"])


def downgrade() -> None:
    # --- Revert curricula ---
    op.drop_index("ix_curricula_organization_id", "curricula")
    op.drop_constraint("fk_curricula_organization_id", "curricula", type_="foreignkey")
    op.drop_column("curricula", "organization_id")

    # --- Revert activation_codes ---
    op.execute(
        "ALTER TABLE activation_codes "
        "DROP CONSTRAINT IF EXISTS ck_activation_codes_curriculum_requires_org"
    )
    op.execute(
        "ALTER TABLE activation_codes DROP CONSTRAINT IF EXISTS ck_activation_codes_org_xor_expert"
    )
    op.execute(
        "ALTER TABLE activation_codes "
        "DROP CONSTRAINT IF EXISTS ck_activation_codes_course_or_curriculum"
    )

    op.drop_index("ix_activation_codes_curriculum_id", "activation_codes")
    op.drop_constraint("fk_activation_codes_curriculum_id", "activation_codes", type_="foreignkey")
    op.drop_column("activation_codes", "curriculum_id")

    op.drop_index("ix_activation_codes_organization_id", "activation_codes")
    op.drop_constraint(
        "fk_activation_codes_organization_id", "activation_codes", type_="foreignkey"
    )
    op.drop_column("activation_codes", "organization_id")

    op.alter_column("activation_codes", "course_id", existing_type=sa.Uuid(), nullable=False)

    # Note: Postgres enum values cannot be removed in downgrade
