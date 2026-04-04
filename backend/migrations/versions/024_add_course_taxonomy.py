"""Add course taxonomy: course_domain[], course_level[], audience_type[] arrays.

Replace free-text domain/target_audience with structured enum array columns
so courses can belong to multiple domains, levels, and audience types.

Revision ID: 024_add_course_taxonomy
Revises: 023_add_admin_syllabus_audit_log
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "024_add_course_taxonomy"
down_revision: str | None = "023_add_admin_syllabus_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_COURSE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # --- Create enum types (idempotent) ---
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE coursedomain AS ENUM (
                'health_sciences', 'natural_sciences', 'social_sciences',
                'mathematics', 'engineering', 'information_technology',
                'education', 'arts_humanities', 'business_management',
                'law', 'agriculture', 'environmental_studies', 'other'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE courselevel AS ENUM (
                'beginner', 'intermediate', 'advanced', 'expert'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE audiencetype AS ENUM (
                'kindergarten', 'primary_school', 'secondary_school',
                'university', 'professional', 'researcher',
                'teacher', 'policy_maker', 'continuing_education'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # --- Add array columns ---
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_domain coursedomain[] DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS course_level courselevel[] DEFAULT '{}'"
    )
    op.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS audience_type audiencetype[] DEFAULT '{}'"
    )

    # --- Migrate existing seed course ---
    op.execute(
        f"""
        UPDATE courses
        SET course_domain = ARRAY['health_sciences']::coursedomain[],
            course_level  = ARRAY['beginner']::courselevel[],
            audience_type = ARRAY['professional']::audiencetype[]
        WHERE id = '{DEFAULT_COURSE_ID}'
        """
    )

    # --- Drop old free-text columns ---
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS domain")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS target_audience")

    # --- Indexes for array filtering (GIN) ---
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courses_course_domain ON courses USING GIN (course_domain)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courses_course_level ON courses USING GIN (course_level)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courses_audience_type ON courses USING GIN (audience_type)"
    )


def downgrade() -> None:
    # Restore old columns
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS domain VARCHAR")
    op.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS target_audience TEXT")

    # Migrate back: pick first element from arrays
    op.execute(
        "UPDATE courses SET domain = course_domain[1]::text "
        "WHERE course_domain IS NOT NULL AND array_length(course_domain, 1) > 0"
    )

    # Drop new columns and indexes
    op.execute("DROP INDEX IF EXISTS ix_courses_course_domain")
    op.execute("DROP INDEX IF EXISTS ix_courses_course_level")
    op.execute("DROP INDEX IF EXISTS ix_courses_audience_type")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS course_domain")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS course_level")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS audience_type")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS coursedomain")
    op.execute("DROP TYPE IF EXISTS courselevel")
    op.execute("DROP TYPE IF EXISTS audiencetype")
