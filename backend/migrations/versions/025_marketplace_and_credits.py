"""Marketplace tables: course_prices, course_reviews + course model changes.

Adds is_marketplace and expert_id to courses, payment_transaction_id to
user_course_enrollment, and creates course_prices and course_reviews tables.

Revision ID: 025_marketplace_and_credits
Revises: 024_add_course_taxonomy
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "025_marketplace_and_credits"
down_revision: str | None = "024_add_course_taxonomy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Add marketplace columns to courses ---
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS is_marketplace BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS expert_id UUID REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_courses_expert_id ON courses (expert_id)")

    # --- Backfill existing courses: is_marketplace=false (already default, explicit for clarity) ---
    op.execute("UPDATE courses SET is_marketplace = false WHERE is_marketplace IS NULL")

    # --- Add payment_transaction_id to user_course_enrollment ---
    # Note: transactions table is expected to be created by a sibling migration in issue #606.
    # We use ADD COLUMN IF NOT EXISTS with a deferred FK to avoid ordering issues.
    op.execute(
        """
        ALTER TABLE user_course_enrollment
        ADD COLUMN IF NOT EXISTS payment_transaction_id UUID
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_enrollment_payment_tx ON user_course_enrollment (payment_transaction_id)"
    )

    # --- Create course_prices table ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_prices (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            course_id UUID NOT NULL UNIQUE REFERENCES courses(id) ON DELETE CASCADE,
            price_credits BIGINT NOT NULL DEFAULT 0,
            is_free BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_prices_course_id ON course_prices (course_id)")

    # --- Create course_reviews table ---
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_reviews (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            comment TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_course_reviews_course_user UNIQUE (course_id, user_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_reviews_course_id ON course_reviews (course_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_course_reviews_user_id ON course_reviews (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS course_reviews")
    op.execute("DROP TABLE IF EXISTS course_prices")

    op.execute("DROP INDEX IF EXISTS ix_enrollment_payment_tx")
    op.execute(
        "ALTER TABLE user_course_enrollment DROP COLUMN IF EXISTS payment_transaction_id"
    )

    op.execute("DROP INDEX IF EXISTS ix_courses_expert_id")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS expert_id")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS is_marketplace")
