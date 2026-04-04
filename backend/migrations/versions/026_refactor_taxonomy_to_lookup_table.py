"""Refactor course taxonomy from PG enums to lookup table.

Replace coursedomain[], courselevel[], audiencetype[] array columns with
taxonomy_categories table + course_taxonomy junction table for admin-managed
taxonomy.

Revision ID: 026_refactor_taxonomy_to_lookup_table
Revises: 025_fix_module_number_unique_per_course
Create Date: 2026-04-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "026_refactor_taxonomy_to_lookup_table"
down_revision: str | None = "025_add_module_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# All seed data: (type, slug, label_fr, label_en, sort_order)
SEED_DATA = [
    # Domains
    ("domain", "health_sciences", "Sciences de la santé", "Health Sciences", 1),
    ("domain", "natural_sciences", "Sciences naturelles", "Natural Sciences", 2),
    ("domain", "social_sciences", "Sciences sociales", "Social Sciences", 3),
    ("domain", "mathematics", "Mathématiques", "Mathematics", 4),
    ("domain", "engineering", "Ingénierie", "Engineering", 5),
    ("domain", "information_technology", "Informatique", "Information Technology", 6),
    ("domain", "education", "Éducation", "Education", 7),
    ("domain", "arts_humanities", "Arts et lettres", "Arts & Humanities", 8),
    ("domain", "business_management", "Gestion et commerce", "Business & Management", 9),
    ("domain", "law", "Droit", "Law", 10),
    ("domain", "agriculture", "Agriculture", "Agriculture", 11),
    ("domain", "environmental_studies", "Études environnementales", "Environmental Studies", 12),
    ("domain", "other", "Autre", "Other", 13),
    # Levels
    ("level", "beginner", "Débutant", "Beginner", 1),
    ("level", "intermediate", "Intermédiaire", "Intermediate", 2),
    ("level", "advanced", "Avancé", "Advanced", 3),
    ("level", "expert", "Expert", "Expert", 4),
    # Audience types
    ("audience", "kindergarten", "Maternelle", "Kindergarten", 1),
    ("audience", "primary_school", "Primaire", "Primary School", 2),
    ("audience", "secondary_school", "Secondaire", "Secondary School", 3),
    ("audience", "university", "Universitaire", "University", 4),
    ("audience", "professional", "Professionnel", "Professional", 5),
    ("audience", "researcher", "Chercheur", "Researcher", 6),
    ("audience", "teacher", "Enseignant", "Teacher", 7),
    ("audience", "policy_maker", "Décideur politique", "Policy Maker", 8),
    ("audience", "continuing_education", "Formation continue", "Continuing Education", 9),
]


def upgrade() -> None:
    # 1. Create taxonomy_categories table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS taxonomy_categories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            type VARCHAR(20) NOT NULL,
            slug VARCHAR(100) NOT NULL,
            label_fr TEXT NOT NULL,
            label_en TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(type, slug),
            CHECK(type IN ('domain', 'level', 'audience'))
        )
        """
    )

    # 2. Seed taxonomy_categories with existing enum values + labels
    for cat_type, slug, label_fr, label_en, sort_order in SEED_DATA:
        label_fr_escaped = label_fr.replace("'", "''")
        label_en_escaped = label_en.replace("'", "''")
        op.execute(
            f"INSERT INTO taxonomy_categories (type, slug, label_fr, label_en, sort_order) "
            f"VALUES ('{cat_type}', '{slug}', '{label_fr_escaped}', "
            f"'{label_en_escaped}', {sort_order}) "
            f"ON CONFLICT (type, slug) DO NOTHING"
        )

    # 3. Create course_taxonomy junction table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS course_taxonomy (
            course_id UUID NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            category_id UUID NOT NULL REFERENCES taxonomy_categories(id) ON DELETE RESTRICT,
            PRIMARY KEY (course_id, category_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_course_taxonomy_course_id ON course_taxonomy (course_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_course_taxonomy_category_id ON course_taxonomy (category_id)"
    )

    # 4. Migrate existing data from array columns to junction table
    # For each array column type, unnest and join to taxonomy_categories
    for col, cat_type in [
        ("course_domain", "domain"),
        ("course_level", "level"),
        ("audience_type", "audience"),
    ]:
        op.execute(
            f"""
            INSERT INTO course_taxonomy (course_id, category_id)
            SELECT c.id, tc.id
            FROM courses c,
                 LATERAL unnest(c.{col}::text[]) AS val
            JOIN taxonomy_categories tc ON tc.slug = val AND tc.type = '{cat_type}'
            WHERE c.{col} IS NOT NULL AND array_length(c.{col}, 1) > 0
            ON CONFLICT DO NOTHING
            """
        )

    # 5. Drop old array columns and indexes
    op.execute("DROP INDEX IF EXISTS ix_courses_course_domain")
    op.execute("DROP INDEX IF EXISTS ix_courses_course_level")
    op.execute("DROP INDEX IF EXISTS ix_courses_audience_type")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS course_domain")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS course_level")
    op.execute("ALTER TABLE courses DROP COLUMN IF EXISTS audience_type")

    # 6. Drop old enum types
    op.execute("DROP TYPE IF EXISTS coursedomain")
    op.execute("DROP TYPE IF EXISTS courselevel")
    op.execute("DROP TYPE IF EXISTS audiencetype")


def downgrade() -> None:
    # Recreate enum types
    op.execute(
        "CREATE TYPE coursedomain AS ENUM ("
        "'health_sciences','natural_sciences','social_sciences',"
        "'mathematics','engineering','information_technology',"
        "'education','arts_humanities','business_management',"
        "'law','agriculture','environmental_studies','other')"
    )
    op.execute("CREATE TYPE courselevel AS ENUM ('beginner','intermediate','advanced','expert')")
    op.execute(
        "CREATE TYPE audiencetype AS ENUM ("
        "'kindergarten','primary_school','secondary_school',"
        "'university','professional','researcher',"
        "'teacher','policy_maker','continuing_education')"
    )

    # Re-add array columns
    op.execute("ALTER TABLE courses ADD COLUMN course_domain coursedomain[] DEFAULT '{}'")
    op.execute("ALTER TABLE courses ADD COLUMN course_level courselevel[] DEFAULT '{}'")
    op.execute("ALTER TABLE courses ADD COLUMN audience_type audiencetype[] DEFAULT '{}'")

    # Migrate data back from junction table
    for col, cat_type, enum_type in [
        ("course_domain", "domain", "coursedomain"),
        ("course_level", "level", "courselevel"),
        ("audience_type", "audience", "audiencetype"),
    ]:
        op.execute(
            f"""
            UPDATE courses c SET {col} = sub.slugs::{enum_type}[]
            FROM (
                SELECT ct.course_id, array_agg(tc.slug) AS slugs
                FROM course_taxonomy ct
                JOIN taxonomy_categories tc ON tc.id = ct.category_id
                WHERE tc.type = '{cat_type}'
                GROUP BY ct.course_id
            ) sub
            WHERE c.id = sub.course_id
            """
        )

    # Re-add GIN indexes
    op.execute("CREATE INDEX ix_courses_course_domain ON courses USING GIN (course_domain)")
    op.execute("CREATE INDEX ix_courses_course_level ON courses USING GIN (course_level)")
    op.execute("CREATE INDEX ix_courses_audience_type ON courses USING GIN (audience_type)")

    # Drop new tables
    op.execute("DROP INDEX IF EXISTS ix_course_taxonomy_category_id")
    op.execute("DROP INDEX IF EXISTS ix_course_taxonomy_course_id")
    op.execute("DROP TABLE IF EXISTS course_taxonomy")
    op.execute("DROP TABLE IF EXISTS taxonomy_categories")
