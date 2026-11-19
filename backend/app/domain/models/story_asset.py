"""The pictures a module's story may show, kept apart from the story (#2709).

One row per module: the asset catalogue ``story_assets.build_catalogue`` made
(course figures and lesson illustrations, by code, with no model call) and the
binding of the story's props to it. It is a table of its own, not a field of
the module story row, because that row is rewritten whole at every re-merge
and is one per language, while the catalogue is built once, carries both
languages, and must outlive a regeneration of the story.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class StoryAssetCatalogue(Base):
    """A module's catalogue ``A1..An``, its pins and exclusions, and its prop binding."""

    __tablename__ = "story_asset_catalogues"

    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True
    )
    #: ``story_assets.CATALOGUE_VERSION`` the content was built with.
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    #: ``{"course_id", "source", "entries": [...], "gaps": [...], "pins": [...],
    #: "exclusions": [...], "binding": {prop id: entry id}}``.
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
