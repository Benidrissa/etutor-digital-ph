"""Add courses and user_course_enrollments tables; seed default course; auto-enroll existing users.

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
DEFAULT_COURSE_SLUG = "sante-publique-aof"


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(), nullable=False, unique=True),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("description_fr", sa.Text(), nullable=True),
        sa.Column("description_en", sa.Text(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("target_audience", sa.Text(), nullable=True),
        sa.Column("languages", sa.String(), nullable=False, server_default="fr,en"),
        sa.Column("estimated_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("module_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
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
    op.create_index("ix_courses_slug", "courses", ["slug"])
    op.create_index("ix_courses_rag_collection_id", "courses", ["rag_collection_id"])
    op.create_index("ix_courses_status", "courses", ["status"])

    op.create_table(
        "user_course_enrollments",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("completion_pct", sa.Float(), nullable=False, server_default="0.0"),
        sa.UniqueConstraint("user_id", "course_id", name="uq_user_course"),
    )

    op.add_column(
        "modules",
        sa.Column(
            "course_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index("ix_modules_course_id", "modules", ["course_id"])

    op.execute(
        f"""
        INSERT INTO courses (id, slug, title_fr, title_en, description_fr, description_en,
                             domain, target_audience, languages, estimated_hours,
                             module_count, status, published_at)
        VALUES (
            '{DEFAULT_COURSE_ID}',
            '{DEFAULT_COURSE_SLUG}',
            'Santé Publique AOF',
            'Public Health AOF',
            'Formation adaptative bilingue en santé publique pour les professionnels de santé d''Afrique de l''Ouest. Couvre 4 niveaux progressifs, 15 modules, ~320 heures.',
            'Adaptive bilingual public health training for health professionals in West Africa. Covers 4 progressive levels, 15 modules, ~320 hours.',
            'Santé Publique',
            'Professionnels de santé en Afrique de l''Ouest (agents communautaires, infirmiers, médecins, épidémiologistes)',
            'fr,en',
            320,
            15,
            'published',
            NOW()
        )
        """
    )

    op.execute(
        f"""
        INSERT INTO user_course_enrollments (user_id, course_id, enrolled_at, status, completion_pct)
        SELECT id, '{DEFAULT_COURSE_ID}', NOW(), 'active', 0.0
        FROM users
        ON CONFLICT (user_id, course_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_modules_course_id", table_name="modules")
    op.drop_column("modules", "course_id")

    op.drop_table("user_course_enrollments")

    op.drop_index("ix_courses_status", table_name="courses")
    op.drop_index("ix_courses_rag_collection_id", table_name="courses")
    op.drop_index("ix_courses_slug", table_name="courses")
    op.drop_table("courses")
