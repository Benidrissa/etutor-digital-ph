"""fix generated_images FK constraints to SET NULL on delete

Revision ID: 094_fix_generated_images_fk_set_null
Revises: 093_fix_audit_log_schema
Create Date: 2026-05-16

The generated_images table has two FK constraints that are NO ACTION in the DB
despite the SQLAlchemy model declaring ondelete="SET NULL". This causes course
deletion to fail with a ForeignKeyViolationError when the delete cascades from
courses -> modules and PostgreSQL tries to delete modules rows referenced by
generated_images.module_id.

Both generated_images_module_id_fkey and generated_images_lesson_id_fkey are
affected. generated_audio equivalents are already SET NULL and do not need fixing.
"""

from alembic import op

revision: str = "094_fix_generated_images_fk_set_null"
down_revision: str | None = "093_fix_audit_log_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # generated_images.module_id → modules.id
    op.drop_constraint(
        "generated_images_module_id_fkey", "generated_images", type_="foreignkey"
    )
    op.create_foreign_key(
        "generated_images_module_id_fkey",
        "generated_images",
        "modules",
        ["module_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # generated_images.lesson_id → generated_content.id
    op.drop_constraint(
        "generated_images_lesson_id_fkey", "generated_images", type_="foreignkey"
    )
    op.create_foreign_key(
        "generated_images_lesson_id_fkey",
        "generated_images",
        "generated_content",
        ["lesson_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "generated_images_lesson_id_fkey", "generated_images", type_="foreignkey"
    )
    op.create_foreign_key(
        "generated_images_lesson_id_fkey",
        "generated_images",
        "generated_content",
        ["lesson_id"],
        ["id"],
    )

    op.drop_constraint(
        "generated_images_module_id_fkey", "generated_images", type_="foreignkey"
    )
    op.create_foreign_key(
        "generated_images_module_id_fkey",
        "generated_images",
        "modules",
        ["module_id"],
        ["id"],
    )
