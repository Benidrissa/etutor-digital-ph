"""fix admin_audit_logs schema: add target_user_email, convert details jsonb→text

Revision ID: 093_fix_audit_log_schema
Revises: 092_fix_cascade_fk_module_units_summative_attempts
Create Date: 2026-05-15

Two schema bugs found during demo tenant UAT:

1. target_user_email VARCHAR column was missing from admin_audit_logs.
   The AuditLog SQLAlchemy model defines it, but the column was never added
   via migration — the table was originally created before this field existed.

2. details column was created as JSONB in some tenants, while the model
   defines it as Text. This causes DatatypeMismatchError when inserting
   audit log rows (e.g. on POST /admin/users).

Both issues affect the santepublique_aof baseline used to clone all new
tenant schemas, so every tenant provisioned before this migration runs will
have the same bugs. This migration is idempotent: it uses IF NOT EXISTS /
conditional type-change so it is safe to run multiple times or on tenants
that already have the correct schema.
"""

from alembic import op


revision = "093_fix_audit_log_schema"
down_revision = "092_fix_cascade_fk_module_units_summative_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add target_user_email if it doesn't exist
    op.execute("""
        ALTER TABLE admin_audit_logs
        ADD COLUMN IF NOT EXISTS target_user_email VARCHAR;
    """)

    # 2. Convert details from jsonb to text only if currently jsonb
    #    (tenants that already have TEXT are unaffected)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'admin_audit_logs'
                  AND column_name = 'details'
                  AND data_type = 'jsonb'
            ) THEN
                ALTER TABLE admin_audit_logs
                    ALTER COLUMN details TYPE TEXT USING (details::text);
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # target_user_email: drop the column (safe — was missing before)
    op.execute("""
        ALTER TABLE admin_audit_logs
        DROP COLUMN IF EXISTS target_user_email;
    """)

    # details: convert text back to jsonb (best-effort; may fail on non-JSON values)
    op.execute("""
        ALTER TABLE admin_audit_logs
            ALTER COLUMN details TYPE JSONB USING (details::jsonb);
    """)
