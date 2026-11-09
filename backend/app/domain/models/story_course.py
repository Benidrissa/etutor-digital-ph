"""Persistence for ``story-course/1`` course files.

One row is one week of work: the authored course file kept whole in ``content``,
with the fields the catalog and the admin screens query lifted out alongside it.

The file is stored as authored rather than normalised into tables on purpose.
It is a single versioned document that the player downloads in one piece for
offline use, and its format is versioned independently of this schema, so
shredding it across a dozen tables would buy nothing and would silently drop
any field a later format version adds.

A row is one of three kinds:

* a **hand-authored week** (``module_id IS NULL``) — the original use; every
  binding column below is null;
* a **chapter** (``module_unit_id IS NOT NULL``) — the story of one lesson
  unit, slug ``lesson-{unit hex}-{lang}``, generated from that unit's lesson
  and the quiz of the quiz unit covering it (migration 106). It is bound to
  ``(module_unit_id, language)`` and remembers which lesson and quiz rows it
  was derived from — with the revision and a content digest of each — so it
  goes stale, and is regenerated, when either source is regenerated or
  edited. It is the cache of one chapter of its module's story;
* a **module story** (``module_id IS NOT NULL AND module_unit_id IS NULL``) —
  one story per ``(module_id, language)``, slug ``module-{module hex}-{lang}``,
  assembled deterministically from the module's chapters (migration 107). Its
  manifest (``source_rows``) records the assembler version and, per unit, the
  chapter row it was merged from; ``source_units_digest`` is a digest of the
  module's roster. A changed roster, or any chapter row changed or stale,
  makes it stale.
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
        # One module story per module and language (migration 107). Partial,
        # because a module's chapter rows share its module_id and language.
        Index(
            "uq_story_courses_module_story",
            "module_id",
            "language",
            unique=True,
            postgresql_where=sa.text("module_unit_id IS NULL"),
        ),
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

    #: The module and unit whose lesson this story tells. A module story has
    #: the module and no unit.
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

    #: The quiz the story's questions were derived from — that of the quiz
    #: unit covering the lesson, never the lesson unit's own — and its
    #: revision. Both null when there was no cached quiz; a non-null revision
    #: with a null id means the quiz row was deleted since.
    source_quiz_content_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("generated_content.id", ondelete="SET NULL"), nullable=True
    )
    source_quiz_revision: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    #: sha256 of each source row's content as canonical JSON (sorted keys, no
    #: whitespace). An admin's manual edit of a lesson changes its content
    #: without bumping ``content_revision`` (an edit of a quiz does bump it);
    #: the digest catches either.
    source_lesson_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_quiz_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # -- module binding (migration 107); null for every other kind ----------

    #: A module story's manifest: ``{"assembler": int, "units": [{
    #: "module_unit_id", "unit_number", "role", "status", "chapter_story_id",
    #: "chapter_updated_at"}, ...]}``, one entry per unit in teaching order.
    source_rows: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: sha256 of the module's roster as canonical JSON: ``[[id, unit_number,
    #: order_index, role, title_en, title_fr], ...]`` in teaching order.
    source_units_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # TIMESTAMP WITH TIME ZONE, as migration 105 creates them.
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    course: Mapped[Course | None] = relationship("Course", foreign_keys=[course_id])
    author: Mapped[User | None] = relationship("User", foreign_keys=[created_by])
