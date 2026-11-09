"""The story bible of a course: one cast and one set of places (#2674).

Every module story of a course is told by the same characters in the same
places, so the art made for them (#2675) is made once per course. The bible
is written by one model call the first time a story of the course is
generated, then reused by every module story, in every language (its titles
are bilingual and its names neutral).

``content`` holds ``{"version", "audience", "country", "cast", "places",
"facts", "missions"}`` (see :mod:`app.domain.services.story_bible`);
``digest`` is the sha256 of ``content`` as canonical JSON. A module story and
its chapters record the digest they were told with: a bible that is replaced
(an admin deletes the row) makes them stale.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base


class StoryCourseBible(Base):
    """A course's story cast and places."""

    __tablename__ = "story_course_bibles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: One bible per course.
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    #: sha256 of ``content`` as canonical JSON (sorted keys, no whitespace).
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The model that wrote it (empty when the bible was built without one).
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
