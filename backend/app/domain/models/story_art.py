"""Generated cartoon art for story mode (#2675): character poses and place backdrops.

One course has one cast and one set of places (the course "bible" written into
every story document of the course, #2674), so the art is stored per course:
one row per ``(course_id, kind, key, pose)``.

* ``kind="character"``: ``key`` is the cast id (``mentor``, ``margo``...), or
  ``hero:<variant>`` for the learner's hero (``hero:girl``, ``hero:boy``);
  ``pose`` is one of :data:`CHARACTER_POSES`. The idle pose is generated
  first; the others are image edits of it, so the face and outfit stay the same.
* ``kind="place"``: ``key`` is the place id; ``pose`` is ``backdrop``.

``look_digest`` is the digest of the look sentence the image was drawn from
(:func:`app.domain.services.story_art_service.look_digest`) and
``art_version`` the version of the prompts and post-processing: a look that is
not the course's any more, or an older version, makes the row stale and it is drawn
again. A row is ``ready`` (``image_data`` holds a WebP; characters keep their
alpha channel) or ``failed`` (``error`` says why). A deterministic failure is
final until the look changes, so a refused prompt never costs more than its
two attempts; a transient one is tried again by later runs after a backoff
(``failed_runs``, ``retry_after``), then given up.

Every stored image gets a fresh ``id``: the data route serves it as immutable,
so a redrawn image must never reuse the URL of the one it replaces.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.models.base import Base

KIND_CHARACTER = "character"
KIND_PLACE = "place"
KINDS = (KIND_CHARACTER, KIND_PLACE)

POSE_IDLE = "idle"
#: A character's poses, in the order they are made (idle first: the others are
#: edits of it).
CHARACTER_POSES = (POSE_IDLE, "talk", "happy", "think")
POSE_BACKDROP = "backdrop"
POSES = (*CHARACTER_POSES, POSE_BACKDROP)

STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUSES = (STATUS_READY, STATUS_FAILED)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class StoryArt(Base):
    """One generated image of a course's story art."""

    __tablename__ = "story_art"
    __table_args__ = (
        UniqueConstraint("course_id", "kind", "key", "pose", name="uq_story_art_course_item"),
        CheckConstraint(_in("kind", KINDS), name="ck_story_art_kind"),
        CheckConstraint(_in("pose", POSES), name="ck_story_art_pose"),
        CheckConstraint(_in("status", STATUSES), name="ck_story_art_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    pose: Mapped[str] = mapped_column(String(16), nullable=False)
    #: sha256 of the (normalised) look the image was drawn from; the art version
    #: is not part of it (``art_version``).
    look_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The WebP. Deferred: the art map reads every row of a course on each story
    #: view and needs none of the bytes; only the data route loads them.
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True, deferred=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: A ready row: the image model that drew it (after any routing or fallback).
    #: A failed row: the configured model (``ai-model-image``) it failed under;
    #: a run under another model tries it again (#2689).
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The art version (prompts and post-processing) it was drawn with; a row of
    #: an older version is redrawn (``story_art_service.ART_VERSION``).
    art_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    #: A ``failed`` row: how many runs in a row failed it for this look with a
    #: transient error (outage, quota, timeout), and when a run may try it
    #: again. ``retry_after`` is null for a final failure: a deterministic one
    #: (a refused prompt, an unusable image), or a transient one given up.
    failed_runs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_after: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
