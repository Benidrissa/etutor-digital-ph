"""Add courses and user_course_enrollment tables, add course_id FK to modules.

Revision ID: 021_add_courses_and_enrollment
Revises: 020_add_admin_audit_logs_table
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "021_add_courses_and_enrollment"
down_revision: str | None = "020_add_admin_audit_logs_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_COURSE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # Use raw SQL for entire courses table to avoid SQLAlchemy auto-creating enums
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE coursestatus AS ENUM ('draft', 'published', 'archived');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE enrollmentstatus AS ENUM ('active', 'completed', 'dropped');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS courses (
            id UUID PRIMARY KEY,
            slug VARCHAR NOT NULL,
            title_fr TEXT NOT NULL,
            title_en TEXT NOT NULL,
            description_fr TEXT,
            description_en TEXT,
            domain VARCHAR,
            target_audience TEXT,
            languages VARCHAR NOT NULL DEFAULT 'fr,en',
            estimated_hours INTEGER NOT NULL DEFAULT 20,
            module_count INTEGER NOT NULL DEFAULT 0,
            status coursestatus NOT NULL DEFAULT 'draft',
            cover_image_url VARCHAR,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            rag_collection_id VARCHAR,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at TIMESTAMPTZ
        )
        """
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_index("ix_courses_status", "courses", ["status"])

    op.execute(
        f"""
        INSERT INTO courses (id, slug, title_fr, title_en, description_fr, description_en,
                             domain, estimated_hours, module_count, status, languages,
                             created_at, published_at)
        VALUES (
            '{DEFAULT_COURSE_ID}',
            'sante-publique-aof',
            'Santé Publique AOF',
            'Public Health AOF',
            'Parcours adaptatif de santé publique pour les professionnels de santé en Afrique de l''Ouest. 4 niveaux, 15 modules, ~320 heures.',
            'Adaptive public health course for health professionals in West Africa. 4 levels, 15 modules, ~320 hours.',
            'Santé Publique',
            320,
            15,
            'published',
            'fr,en',
            NOW(),
            NOW()
        )
        """
    )

    op.add_column(
        "modules",
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_modules_course_id", "modules", ["course_id"])

    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS user_course_enrollment (
            user_id UUID REFERENCES users(id) NOT NULL,
            course_id UUID REFERENCES courses(id) NOT NULL,
            enrolled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            status enrollmentstatus NOT NULL DEFAULT 'active',
            completion_pct FLOAT NOT NULL DEFAULT 0.0,
            PRIMARY KEY (user_id, course_id)
        )
        """
    )
    op.create_index("ix_user_course_enrollment_user_id", "user_course_enrollment", ["user_id"])
    op.create_index("ix_user_course_enrollment_course_id", "user_course_enrollment", ["course_id"])

    op.execute(
        f"""
        INSERT INTO user_course_enrollment (user_id, course_id, enrolled_at, status, completion_pct)
        SELECT id, '{DEFAULT_COURSE_ID}', NOW(), 'active', 0.0
        FROM users
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_course_enrollment_course_id", table_name="user_course_enrollment")
    op.drop_index("ix_user_course_enrollment_user_id", table_name="user_course_enrollment")
    op.drop_table("user_course_enrollment")

    op.drop_index("ix_modules_course_id", table_name="modules")
    op.drop_column("modules", "course_id")

    op.drop_index("ix_courses_status", table_name="courses")
    op.drop_index("ix_courses_slug", table_name="courses")
    op.drop_table("courses")

    op.execute("DROP TYPE coursestatus")
    op.execute("DROP TYPE enrollmentstatus")
