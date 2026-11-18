"""Add story_module_plans: the episode plan of a module story (#2680).

Story generator v4 plans a module as one episode — premise, props, each
chapter's beats and hook, the rally — before it tells the chapters in order.
One row per (module, language): the plan (``content`` JSONB), the digest of
what it was made from (``inputs``), its own ``digest`` and ``global_digest``
(the plan without its chapters, which every chapter records), the plan
``version``, the ``model`` that wrote it ("DEFAULTED" for a plan made in
code) and timestamps. Deleting the module deletes its plans.

The upgrade is additive and changes no other table: a chapter's link to its
plan lives in its document (``sira_chapter``). The downgrade drops the table.

Revision ID: 110_story_module_plans
Revises: 109_story_art
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "110_story_module_plans"
down_revision = "109_story_art"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_module_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "module_id",
            UUID(as_uuid=True),
            sa.ForeignKey("modules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(5), nullable=False),
        sa.Column("version", sa.SmallInteger(), nullable=False),
        sa.Column("inputs", sa.String(64), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("global_digest", sa.String(64), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("module_id", "language", name="uq_story_module_plans_module_language"),
    )


def downgrade() -> None:
    op.drop_table("story_module_plans")
