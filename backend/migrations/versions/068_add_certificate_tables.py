"""Add certificate_templates and certificates tables.

Revision ID: 068
Revises: 067
Create Date: 2026-04-16

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def _create_enum_if_not_exists(name: str, values: list[str]) -> None:
    """Create a PostgreSQL enum type only if it doesn't already exist."""
    conn = op.get_bind()
    vals = ", ".join(f"'{v}'" for v in values)
    conn.execute(
        sa.text(
            f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
            f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
        )
    )


def upgrade() -> None:
    _create_enum_if_not_exists("certificatestatus", ["valid", "revoked"])

    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "course_id",
            sa.Uuid(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("title_fr", sa.Text(), nullable=False),
        sa.Column("title_en", sa.Text(), nullable=False),
        sa.Column("organization_name", sa.Text(), nullable=True),
        sa.Column("signatory_name", sa.Text(), nullable=True),
        sa.Column("signatory_title", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(500), nullable=True),
        sa.Column("additional_text_fr", sa.Text(), nullable=True),
        sa.Column("additional_text_en", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "certificates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("certificate_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "course_id",
            sa.Uuid(),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("verification_code", sa.String(20), nullable=False, unique=True, index=True),
        sa.Column("average_score", sa.Float(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pdf_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.Enum("valid", "revoked", name="certificatestatus", create_type=False),
            server_default="valid",
            nullable=False,
        ),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "course_id", name="uq_certificate_user_course"),
    )


def downgrade() -> None:
    op.drop_table("certificates")
    op.drop_table("certificate_templates")
    op.execute("DROP TYPE IF EXISTS certificatestatus")
