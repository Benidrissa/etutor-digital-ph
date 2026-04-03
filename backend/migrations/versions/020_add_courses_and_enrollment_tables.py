"""Add courses, user_course_enrollments tables and modules.course_id FK

Revision ID: 020_add_courses_and_enrollment_tables
Revises: 019_hash_email_otp_codes
Create Date: 2026-04-02

Data migration:
- Seeds the default SantePublique AOF course (all 15 modules, 320h)
- Auto-enrolls ALL existing users into that course
- Links all existing modules to the default course
- No regression: current learner progression is preserved
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "020_add_courses_and_enrollment_tables"
down_revision: str | None = "019_hash_email_otp_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_COURSE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
DEFAULT_COURSE_SLUG = "sante-publique-aof"


def upgrade() -> None:
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
        sa.Column("languages", postgresql.ARRAY(sa.String()), server_default="{}"),
        sa.Column("estimated_hours", sa.Integer(), server_default="20"),
        sa.Column("module_count", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(), server_default="draft"),
        sa.Column("cover_image_url", sa.Text(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rag_collection_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_courses_slug", "courses", ["slug"], unique=True)
    op.create_index("idx_courses_status", "courses", ["status"])
    op.create_index("idx_courses_domain", "courses", ["domain"])

    op.create_table(
        "user_course_enrollments",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("status", sa.String(), server_default="active"),
        sa.Column("completion_pct", sa.Float(), server_default="0.0"),
        sa.PrimaryKeyConstraint("user_id", "course_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
    )
    op.create_index("idx_enrollment_user_id", "user_course_enrollments", ["user_id"])
    op.create_index("idx_enrollment_course_id", "user_course_enrollments", ["course_id"])
    op.create_index("idx_enrollment_status", "user_course_enrollments", ["status"])

    op.add_column(
        "modules",
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("idx_modules_course_id", "modules", ["course_id"])
    op.create_foreign_key(
        "fk_modules_course_id",
        "modules",
        "courses",
        ["course_id"],
        ["id"],
    )

    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO courses (
                id, slug, title_fr, title_en,
                description_fr, description_en,
                domain, target_audience,
                languages, estimated_hours, module_count,
                status, rag_collection_id,
                created_at, published_at
            ) VALUES (
                :id, :slug, :title_fr, :title_en,
                :description_fr, :description_en,
                :domain, :target_audience,
                ARRAY['fr','en'], :estimated_hours, :module_count,
                'published', :rag_collection_id,
                now(), now()
            )
            """
        ),
        {
            "id": str(DEFAULT_COURSE_ID),
            "slug": DEFAULT_COURSE_SLUG,
            "title_fr": "Santé Publique en Afrique de l'Ouest",
            "title_en": "Public Health in West Africa",
            "description_fr": (
                "Formation complète en santé publique pour les professionnels "
                "de santé d'Afrique de l'Ouest francophone. 4 niveaux, 15 modules, "
                "~320 heures. Contenu adapté au contexte de la CEDEAO."
            ),
            "description_en": (
                "Comprehensive public health training for health professionals "
                "in French-speaking West Africa. 4 levels, 15 modules, ~320 hours. "
                "Content adapted to the ECOWAS context."
            ),
            "domain": "Santé Publique",
            "target_audience": (
                "Professionnels de santé, agents de santé communautaire, "
                "épidémiologistes et gestionnaires de programmes de santé en Afrique de l'Ouest"
            ),
            "estimated_hours": 320,
            "module_count": 15,
            "rag_collection_id": f"course_{DEFAULT_COURSE_SLUG}",
        },
    )

    conn.execute(
        sa.text("UPDATE modules SET course_id = :course_id WHERE course_id IS NULL"),
        {"course_id": str(DEFAULT_COURSE_ID)},
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO user_course_enrollments (user_id, course_id, enrolled_at, status, completion_pct)
            SELECT id, :course_id, now(), 'active', 0.0
            FROM users
            ON CONFLICT (user_id, course_id) DO NOTHING
            """
        ),
        {"course_id": str(DEFAULT_COURSE_ID)},
    )


def downgrade() -> None:
    op.drop_constraint("fk_modules_course_id", "modules", type_="foreignkey")
    op.drop_index("idx_modules_course_id", table_name="modules")
    op.drop_column("modules", "course_id")
    op.drop_table("user_course_enrollments")
    op.drop_table("courses")
