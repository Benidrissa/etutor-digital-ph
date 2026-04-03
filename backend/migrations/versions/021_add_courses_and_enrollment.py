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
    op.execute(
        """
        CREATE TYPE coursestatus AS ENUM ('draft', 'published', 'archived')
        """
    )
    op.execute(
        """
        CREATE TYPE enrollmentstatus AS ENUM ('active', 'completed', 'dropped')
        """
    )

    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("languages", sa.String(), nullable=False, server_default="fr,en"),
        sa.Column("estimated_hours", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("module_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.Enum("draft", "published", "archived", name="coursestatus", create_type=False),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("cover_image_url", sa.String(), nullable=True),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rag_collection_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
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

    op.create_table(
        "user_course_enrollment",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id"),
            primary_key=True,
        ),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "dropped", name="enrollmentstatus", create_type=False),
            nullable=False,
            server_default="active",
        ),
        sa.Column("completion_pct", sa.Float(), nullable=False, server_default="0.0"),
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
