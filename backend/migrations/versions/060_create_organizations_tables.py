"""Create organizations and organization_members tables, extend credit_accounts.

Revision ID: 060
Revises: 059
Create Date: 2026-04-13

"""

import sqlalchemy as sa
from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Create orgmemberrole enum ---
    orgmemberrole = sa.Enum("owner", "admin", "viewer", name="orgmemberrole")
    orgmemberrole.create(op.get_bind(), checkfirst=True)

    # --- Create organizations table ---
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(), nullable=True),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("credit_account_id", sa.Uuid(), nullable=True),
        sa.Column("user_group_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.ForeignKeyConstraint(
            ["credit_account_id"],
            ["credit_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_group_id"],
            ["user_groups.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # --- Create organization_members table ---
    op.create_table(
        "organization_members",
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", orgmemberrole, nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_member"),
    )
    op.create_index("ix_org_members_user_id", "organization_members", ["user_id"])

    # --- Extend credit_accounts: add organization_id, make user_id nullable ---
    # Drop the existing unique constraint on user_id (name may vary)
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE credit_accounts DROP CONSTRAINT IF EXISTS credit_accounts_user_id_key; "
        "ALTER TABLE credit_accounts DROP CONSTRAINT IF EXISTS uq_credit_accounts_user_id; "
        "EXCEPTION WHEN undefined_object THEN NULL; END $$"
    )

    # Make user_id nullable
    op.alter_column("credit_accounts", "user_id", existing_type=sa.Uuid(), nullable=True)

    # Add organization_id column
    op.add_column(
        "credit_accounts",
        sa.Column("organization_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_credit_accounts_organization_id",
        "credit_accounts",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_credit_accounts_organization_id",
        "credit_accounts",
        ["organization_id"],
    )

    # Add partial unique indexes (replacing the old simple unique)
    op.execute(
        "CREATE UNIQUE INDEX ix_credit_accounts_user_id_unique "
        "ON credit_accounts (user_id) WHERE user_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_credit_accounts_organization_id_unique "
        "ON credit_accounts (organization_id) WHERE organization_id IS NOT NULL"
    )

    # Add CHECK: exactly one of user_id or organization_id must be set
    op.execute(
        "ALTER TABLE credit_accounts ADD CONSTRAINT ck_credit_accounts_owner_xor "
        "CHECK ((user_id IS NOT NULL) != (organization_id IS NOT NULL))"
    )


def downgrade() -> None:
    # Remove CHECK constraint
    op.execute("ALTER TABLE credit_accounts DROP CONSTRAINT IF EXISTS ck_credit_accounts_owner_xor")

    # Remove partial unique indexes
    op.execute("DROP INDEX IF EXISTS ix_credit_accounts_organization_id_unique")
    op.execute("DROP INDEX IF EXISTS ix_credit_accounts_user_id_unique")

    # Remove organization_id column
    op.drop_index("ix_credit_accounts_organization_id", "credit_accounts")
    op.drop_constraint("fk_credit_accounts_organization_id", "credit_accounts", type_="foreignkey")
    op.drop_column("credit_accounts", "organization_id")

    # Make user_id non-nullable again
    op.alter_column("credit_accounts", "user_id", existing_type=sa.Uuid(), nullable=False)

    # Restore unique constraint on user_id
    op.create_unique_constraint("credit_accounts_user_id_key", "credit_accounts", ["user_id"])

    # Drop tables
    op.drop_table("organization_members")
    op.drop_table("organizations")

    # Drop enum
    sa.Enum(name="orgmemberrole").drop(op.get_bind(), checkfirst=True)
