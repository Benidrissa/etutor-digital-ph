"""Add update_api_key to adminaction enum.

Revision ID: 103_add_update_api_key_audit_action
Revises: 102_add_course_resource_id_to_source_images
"""

from alembic import op

revision = "103_add_update_api_key_audit_action"
down_revision = "102_add_course_resource_id_to_source_images"


def upgrade() -> None:
    op.execute("ALTER TYPE adminaction ADD VALUE IF NOT EXISTS 'update_api_key'")


def downgrade() -> None:
    pass
