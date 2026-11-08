"""Persistence for ``story-course/1`` course files.

One row is one week of work: the authored course file kept whole in ``content``,
with the fields the catalog and the admin screens query lifted out alongside it.

The file is stored as authored rather than normalised into tables on purpose.
It is a single versioned document that the player downloads in one piece for
offline use, and its format is versioned independently of this schema, so
shredding it across a dozen tables would buy nothing and would silently drop
any field a later format version adds.

A row is one of two kinds:

* a **hand-authored week** — the original use; every lesson-binding column
  below is null;
* a **lesson story** — the story mode of one lesson unit, generated from that
  unit's lesson and quiz the first time a learner opens it (migration 106).
  It is bound to ``(module_unit_id, language)`` and remembers which lesson and
  quiz rows it was derived from — with the revision and a content digest of
  each — so a story goes stale, and is regenerated, when either source is
  regenerated or edited.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.models.base import Base

if TYPE_CHECKING:
    from app.domain.models.course import Course
    from app.domain.models.user import User


class StoryCourseStatus(enum.StrEnum):
    draft = "draft"
    published = "published"
    archived = "archived"


class StoryCourseRecord(Base):
    """A week's ``course.json`` in the ``story-course/1`` format."""

    __tablename__ = "story_courses"
    __table_args__ = (
        Index("ix_story_courses_course_week", "course_id", "week"),
        Index("ix_story_courses_status", "status"),
        # One lesson story per unit and language. NULLs are distinct in a
        # PostgreSQL unique constraint, so hand-authored weeks (unbound) are
        # unaffected.
        UniqueConstraint("module_unit_id", "language", name="uq_story_courses_unit_language"),
        Index("ix_story_courses_module_language", "module_id", "language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: The format's own ``id`` (e.g. "igcse-maths-u1-w04"); the public handle.
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)

    #: Optional link to a Sira course, so a story week can sit inside a course
    #: catalog. Null keeps the week standalone.
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )

    #: The format's ``course``/``unit`` labels, kept verbatim for display.
    course_label: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    week: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Text objects, lifted out so the catalog needs no JSON traversal.
    title: Mapped[dict] = mapped_column(JSONB, nullable=False)
    languages: Mapped[dict] = mapped_column(JSONB, nullable=False)

    format_version: Mapped[str] = mapped_column(String(40), nullable=False)

    #: The whole authored course file.
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)

    status: Mapped[str] = mapped_column(
        sa.Enum("draft", "published", "archived", name="story_course_status_enum"),
        server_default="draft",
        nullable=False,
    )

    #: Last validation outcome. A week may only be published while valid, so
    #: the report is kept to show the author what still fails.
    is_valid: Mapped[bool] = mapped_column(Boolean, server_default=sa.false(), nullable=False)
    validation_report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    max_points: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)

    # -- lesson binding (migration 106); all null for hand-authored weeks ----

    #: The module and unit whose lesson this story tells.
    module_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("modules.id", ondelete="CASCADE"), nullable=True
    )
    module_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("module_units.id", ondelete="CASCADE"), nullable=True
    )
    #: Language of instruction of the story ("fr" | "en"); the other one is
    #: the home language.
    language: Mapped[str | None] = mapped_column(String(2), nullable=True)

    #: The ``generated_content`` lesson row the story was derived from, and
    #: its ``content_revision`` at the time. A regenerated lesson bumps the
    #: revision, which makes the story stale.
    source_lesson_content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id", ondelete="SET NULL"), nullable=True
    )
    source_lesson_revision: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    #: The quiz the story's questions were derived from — the lesson unit's
    #: own, or that of the quiz unit covering the lesson — and its revision.
    #: Both null when there was no cached quiz; a non-null revision with a
    #: null id means the quiz row was deleted since.
    source_quiz_content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id", ondelete="SET NULL"), nullable=True
    )
    source_quiz_revision: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    #: sha256 of each source row's content as canonical JSON (sorted keys, no
    #: whitespace). An admin's manual edit of a lesson or quiz changes its
    #: content without bumping ``content_revision``; the digest catches it.
    source_lesson_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_quiz_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    course: Mapped[Course | None] = relationship("Course", foreign_keys=[course_id])
    author: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
