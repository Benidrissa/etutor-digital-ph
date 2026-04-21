"""Drop the now-unused ``module_media`` table.

Revision ID: 077
Revises: 076
Create Date: 2026-04-21

Per issue #1802 both audio and video summaries live on
``generated_audio`` (per-lesson). The ``module_media`` table was
only used by the short-lived per-module video feature from #1793
and the never-fully-working per-module audio button. Neither path
is still reachable from code after #1802, so the table is dropped
rather than left as dead schema.

``down_revision = '076'`` keeps the migration chain linear: 075
added ``provider_video_id`` to module_media, 076 added
``media_type``/``provider_video_id``/``media_metadata`` to
``generated_audio``, 077 removes the now-orphan table.

Safe to run: staging and production never produced stable video
rows on module_media (feature flag was only briefly enabled on
staging), so dropping the table doesn't lose product data.
"""

from alembic import op

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_module_media_provider_video_id")
    op.execute("DROP TABLE IF EXISTS module_media CASCADE")
    op.execute("DROP TYPE IF EXISTS media_status_enum")


def downgrade() -> None:
    # Schema recreation intentionally omitted — #1802 deprecated the
    # whole concept of module-scoped media, so there is no sensible
    # way to replay the old shape. If you need to roll back past 077
    # you'll need to restore from a backup.
    pass
