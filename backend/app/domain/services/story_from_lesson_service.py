"""The story of one lesson unit: one chapter of its module's story.

Story mode tells a whole module as one story (:mod:`story_module_service`),
with one chapter per unit. A lesson unit's chapter is made here: the unit's
lesson and the quiz of the quiz unit covering it are turned into a
``story-course/1`` week and stored in ``story_courses`` bound to
``(module_unit_id, language)`` — the chapter cache (contract C-1). The module
story task (:func:`app.tasks.content_generation.generate_module_story_task`)
makes sure the lesson and the covering quiz exist, then calls
:meth:`StoryFromLessonService.get_or_generate_unit_story` once per lesson unit
and assembles the module story from the cached chapters. The front end
substitutes the learner's first name for ``{child}``.

Pipeline of one chapter:

1. read the cached lesson row (generating it through the lesson service only
   when the unit has none and a lesson service was given) and the cached quiz
   of the module's quiz unit that covers the lesson
   (:func:`covering_quiz_unit`) — never the lesson unit's own quiz, which an
   offline download can create, and never a quiz generated here;
2. one model call for the chapter's *screenplay* — scenes at the course
   bible's places, the characters teaching through dialogue — and the
   pedagogy around it (#2674);
3. :func:`app.domain.services.story_repair.build_story_document` — the
   deterministic layer that checks the screenplay against the bible, numbers
   its ids and resolves its question refs;
4. :func:`validate_story_course` (Appendix C), plus the generator's own checks
   (question floor, stem leaks, copy-fallbacks);
5. a bounded repair loop — at most :data:`MAX_REPAIR_CALLS` extra model calls,
   each told the remaining error codes and paths — then every attempt is
   settled and if need be salvaged (model-authored items that still fail are
   dropped), and the best valid result (:func:`outcome_rank`) is kept. A story
   without model content (every answer unreadable or unusable) is never
   published;
6. persist: published and valid, or a draft with its report (the API then
   answers 409 ``story_unavailable``). The validator's ``checks`` block is
   written into the stored document either way (C6). A spine the builder
   cannot use at all still ends as a stored draft, never as an exception, so
   later views get the 409 instead of paying for another generation.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.ai.usage_context import ai_usage_context
from app.api.v1.schemas.story_course import StoryCourse, ValidationIssue, ValidationReport
from app.domain.models.ai_usage_event import FEATURE_LESSON_GENERATION, FEATURE_STORY_GENERATION
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import (
    StoryBible,
    default_bible,
    find_bible,
    mission_for,
)
from app.domain.services.story_course_validator import validate_story_course

logger = structlog.get_logger(__name__)

#: Extra model calls after the first one, each fed the remaining errors.
MAX_REPAIR_CALLS = 2

STORY_FEATURE_FLAG = "story-mode-feature-enabled"

#: Unit types that are not lessons and have no story mode. The same set as the
#: front end's ``NON_LESSON_UNIT_TYPES``: such units are rendered by their own
#: viewers, and a unit with no type (legacy rows) is a lesson.
NON_LESSON_UNIT_TYPES = frozenset({"quiz", "case-study", "scenario"})

#: The ``unit_type`` of the units whose quiz covers the lessons before them.
QUIZ_UNIT_TYPE = "quiz"


class NotALessonUnit(ValueError):
    """Story mode was asked for a quiz, case-study or scenario unit."""


def is_lesson_unit(unit_type: str | None) -> bool:
    return unit_type not in NON_LESSON_UNIT_TYPES


def story_mode_enabled() -> bool:
    """The admin master switch; on by default."""
    from app.domain.services.platform_settings_service import SettingsCache

    return bool(SettingsCache.instance().get(STORY_FEATURE_FLAG, True))


def content_digest(content: Any) -> str:
    """sha256 of a source row's content as canonical JSON.

    Keys sorted, no whitespace in separators, so the digest changes exactly
    when the content does — including an admin's manual edit, which does not
    bump ``content_revision``.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Generation dedup (shared by the API, which claims, and the task, which releases)
# --------------------------------------------------------------------------


#: Compare-and-delete: remove the dedup key only while it still holds the
#: caller's task id, so nobody ever deletes a key another request now owns.
RELEASE_IF_OWNER_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


# --------------------------------------------------------------------------
# Persistence shared with the authoring API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StoryBinding:
    """Which lesson unit a chapter tells, and which source rows it came from.

    The quiz row is the covering quiz unit's; the digests are
    :func:`content_digest` of each row's content.
    """

    module_id: uuid.UUID
    module_unit_id: uuid.UUID
    language: str
    lesson_content_id: uuid.UUID
    lesson_revision: int
    quiz_content_id: uuid.UUID | None = None
    quiz_revision: int | None = None
    lesson_digest: str | None = None
    quiz_digest: str | None = None
    #: v4 (#2680): the chapter's own cache — its practice pack, recap, props
    #: now and the digests it was told with (never sent by the API).
    source_rows: dict[str, Any] | None = None


@dataclass(frozen=True)
class ModuleStoryBinding:
    """A module story: its module and language, manifest and roster digest (C-3).

    ``source_rows`` is ``{"assembler": int, "units": [...]}``; ``units_digest``
    is the sha256 of the module's roster.
    """

    module_id: uuid.UUID
    language: str
    source_rows: dict[str, Any]
    units_digest: str


async def upsert_story_course(
    db: AsyncSession,
    *,
    course: StoryCourse,
    content: dict[str, Any],
    report: ValidationReport,
    course_id: uuid.UUID | None,
    publish: bool,
    created_by: uuid.UUID | None = None,
    binding: StoryBinding | ModuleStoryBinding | None = None,
) -> StoryCourseRecord:
    """Create or update the row for ``course.id`` (its slug). Does not commit.

    Shared by the authoring endpoint, the chapter generator and the module
    story so all write exactly the same columns. A hand-authored week that is
    saved without ``publish`` keeps a ``published`` status (the author is
    editing a live week); a chapter or module story that is not publishable
    is always demoted to ``draft``, so an invalid regeneration can never be
    served.
    """
    record = (
        await db.execute(select(StoryCourseRecord).where(StoryCourseRecord.slug == course.id))
    ).scalar_one_or_none()
    if record is None:
        record = StoryCourseRecord(id=uuid.uuid4(), slug=course.id, created_by=created_by)
        db.add(record)

    record.course_id = course_id
    record.course_label = course.course
    record.unit = course.unit
    record.week = course.week
    record.title = dict(course.title)
    record.languages = course.languages.model_dump()
    record.format_version = course.format
    record.content = content
    record.is_valid = report.ok
    record.validation_report = report.model_dump(mode="json")
    record.max_points = report.checks.max_points
    if publish:
        record.status = "published"
    elif binding is not None or record.status != "published":
        record.status = "draft"

    if isinstance(binding, StoryBinding):
        record.module_id = binding.module_id
        record.module_unit_id = binding.module_unit_id
        record.language = binding.language
        record.source_lesson_content_id = binding.lesson_content_id
        record.source_lesson_revision = binding.lesson_revision
        record.source_quiz_content_id = binding.quiz_content_id
        record.source_quiz_revision = binding.quiz_revision
        record.source_lesson_digest = binding.lesson_digest
        record.source_quiz_digest = binding.quiz_digest
        record.source_rows = binding.source_rows
        record.source_units_digest = None
    elif isinstance(binding, ModuleStoryBinding):
        record.module_id = binding.module_id
        record.module_unit_id = None
        record.language = binding.language
        record.source_lesson_content_id = None
        record.source_lesson_revision = None
        record.source_quiz_content_id = None
        record.source_quiz_revision = None
        record.source_lesson_digest = None
        record.source_quiz_digest = None
        record.source_rows = binding.source_rows
        record.source_units_digest = binding.units_digest
    return record


async def find_unit_story(
    session: AsyncSession, module_unit_id: uuid.UUID, language: str
) -> StoryCourseRecord | None:
    """The chapter row of a lesson unit in ``language``, if any."""
    return (
        await session.execute(
            select(StoryCourseRecord).where(
                StoryCourseRecord.module_unit_id == module_unit_id,
                StoryCourseRecord.language == language,
            )
        )
    ).scalar_one_or_none()


_UNIT_NUMBER_PART_RE = re.compile(r"(\d+)")


def _unit_order(unit: Any) -> tuple[int, tuple[Any, ...]]:
    """Teaching order: ``order_index``, then ``unit_number`` read naturally ("1.10" > "1.9")."""
    number = str(getattr(unit, "unit_number", "") or "")
    parts = tuple(
        (0, int(p), "") if p.isdigit() else (1, 0, p)
        for p in _UNIT_NUMBER_PART_RE.split(number)
        if p
    )
    return (getattr(unit, "order_index", 0) or 0, parts)


def covering_quiz_unit(units: Sequence[Any], lesson_unit_id: uuid.UUID) -> Any | None:
    """The module's quiz unit whose quiz covers a lesson unit, if any.

    Syllabus generation seeds a module's units in teaching order —
    ``order_index`` 0, 1, 2… and ``unit_number`` "m.1", "m.2"… — exactly as the
    syllabus lists them, and the syllabus puts a quiz unit after the lessons it
    tests. So the rule is: **the first quiz-typed unit after the lesson in the
    same module; if there is none after it, the nearest quiz-typed unit before
    it** (a lesson that comes after the module's last quiz). The quiz units
    are not skipped over: when that unit has no cached quiz, the story has no
    quiz-derived questions rather than borrowing a quiz about other lessons.
    ``units`` are the module's units (any objects with ``id``, ``unit_type``,
    ``order_index`` and ``unit_number``).
    """
    ordered = sorted(units, key=_unit_order)
    position = next((i for i, u in enumerate(ordered) if u.id == lesson_unit_id), None)
    if position is None:
        return None
    after = [u for u in ordered[position + 1 :] if u.unit_type == QUIZ_UNIT_TYPE]
    if after:
        return after[0]
    before = [u for u in ordered[:position] if u.unit_type == QUIZ_UNIT_TYPE]
    return before[-1] if before else None


async def find_covering_quiz_unit(session: AsyncSession, lesson_unit_id: uuid.UUID) -> Any | None:
    """:func:`covering_quiz_unit` for a lesson unit, read from the database."""
    module_id = (
        select(ModuleUnit.module_id).where(ModuleUnit.id == lesson_unit_id).scalar_subquery()
    )
    units = (
        await session.execute(
            select(
                ModuleUnit.id,
                ModuleUnit.unit_number,
                ModuleUnit.order_index,
                ModuleUnit.unit_type,
            ).where(ModuleUnit.module_id == module_id)
        )
    ).all()
    return covering_quiz_unit(units, lesson_unit_id)


def covering_quiz_units(units: Sequence[Any]) -> dict[Any, Any | None]:
    """Each unit's covering quiz unit id (:func:`covering_quiz_unit`), or ``None``."""
    out: dict[Any, Any | None] = {}
    for unit in units:
        covering = covering_quiz_unit(units, unit.id)
        out[unit.id] = covering.id if covering is not None else None
    return out


def _source_unchanged(row: Any, revision: int | None, digest: str | None) -> bool:
    """The row exists with the recorded ``content_revision`` and content digest."""
    return (
        row is not None
        and revision is not None
        and (row.content_revision or 1) == revision
        and digest is not None
        and content_digest(row.content) == digest
    )


def _chapter_builder(record: StoryCourseRecord) -> Any:
    content = record.content
    return content.get("sira_builder") if isinstance(content, dict) else None


def chapter_marker_matches(marker: Any, bible_digest: str | None, arc: str | None) -> bool:
    """Whether a chapter's ``sira_chapter`` says it was told with this bible and arc.

    ``arc=None`` checks the bible only.
    """
    if not isinstance(marker, dict) or bible_digest is None:
        return False
    if marker.get("bible") != bible_digest:
        return False
    return arc is None or marker.get("arc") == arc


def _chapter_can_be_fresh(record: StoryCourseRecord, builder: Any) -> bool:
    """What a chapter row must carry before its sources are worth reading."""
    if record.module_unit_id is None or record.module_id is None or not record.language:
        return False
    if builder != repair.CHAPTER_BUILDER_VERSION:
        # Built by an older generator (before #2674: code-assembled scenes
        # around a model "spine", no course bible): rebuild it once.
        return False
    if (
        record.source_lesson_content_id is None
        or record.source_lesson_revision is None
        or record.source_lesson_digest is None
    ):
        return False
    # A recorded quiz revision without its row: the quiz was deleted since
    # (FK SET NULL), or the digest was never written.
    return record.source_quiz_revision is None or (
        record.source_quiz_content_id is not None and record.source_quiz_digest is not None
    )


def _chapter_marker(record: StoryCourseRecord) -> Any:
    content = record.content
    return content.get("sira_chapter") if isinstance(content, dict) else None


def _lesson_unchanged(record: StoryCourseRecord, lesson: Any, marker: Any) -> bool:
    """A v4 chapter (#2680): its lesson's FACT SHEET is unchanged — a prose rewrite
    that keeps the ideas, key points and figures costs nothing. Before v4: the
    lesson row's revision and content digest."""
    if isinstance(marker, dict) and marker.get("fact_sheet"):
        from app.ai.prompts.story_from_lesson import fact_sheet_digest

        return lesson is not None and fact_sheet_digest(lesson.content) == marker["fact_sheet"]
    return _source_unchanged(lesson, record.source_lesson_revision, record.source_lesson_digest)


async def chapters_are_fresh(
    session: AsyncSession,
    records: Sequence[StoryCourseRecord],
    *,
    builders: Sequence[Any] | None = None,
    covering: Mapping[uuid.UUID | None, uuid.UUID | None] | None = None,
    markers: Sequence[Any] | None = None,
    expected: Mapping[uuid.UUID | None, Mapping[str, Any]] | None = None,
) -> list[bool]:
    """:func:`story_sources_are_fresh` for many chapter rows: one query of their sources.

    A chapter is stale when:

    * it was not built by this chapter builder (``content["sira_builder"]``
      is not :data:`story_repair.CHAPTER_BUILDER_VERSION`);
    * its lesson row is gone, regenerated (``content_revision`` moved) or
      edited (its content no longer matches the recorded digest — an admin's
      manual edit of a lesson does not bump the revision);
    * the quiz row it used is gone, regenerated or edited, the same way, or
      is the lesson unit's own quiz (never a source since contract C-1);
    * it was built without a quiz and its covering quiz unit now has one in
      its language.

    The lesson unit's own quiz — the offline download creates one — is never
    a source, so one appearing never makes a chapter stale. Nor does the
    module's roster: a chapter built from a quiz stays fresh while that quiz
    is unchanged, even if a quiz unit is added in between.

    ``builders`` are the records' ``content["sira_builder"]``, for a caller
    that read them in SQL and deferred ``content``; by default they are read
    from each record. ``covering`` maps lesson unit ids to their covering
    quiz unit id (``None``: no quiz unit); without it, the rosters of the
    modules of the chapters built without a quiz are read in one more query.
    Rows that are not chapters (no ``module_unit_id``) are reported stale.
    """
    if builders is None:
        builders = [_chapter_builder(record) for record in records]
    if markers is None:
        markers = [_chapter_marker(record) for record in records]
    results = [False] * len(records)
    candidates = [
        index
        for index, (record, builder) in enumerate(zip(records, builders, strict=True))
        if _chapter_can_be_fresh(record, builder)
    ]
    if not candidates:
        return results

    no_quiz = [i for i in candidates if records[i].source_quiz_revision is None]
    if no_quiz and covering is None:
        module_ids = sorted({records[i].module_id for i in no_quiz}, key=str)
        roster = (
            await session.execute(
                select(
                    ModuleUnit.id,
                    ModuleUnit.module_id,
                    ModuleUnit.unit_number,
                    ModuleUnit.order_index,
                    ModuleUnit.unit_type,
                ).where(ModuleUnit.module_id.in_(module_ids))
            )
        ).all()
        covering = {}
        for module_id in module_ids:
            covering.update(covering_quiz_units([u for u in roster if u.module_id == module_id]))
    covering = covering or {}

    source_ids = [
        source_id
        for i in candidates
        for source_id in (records[i].source_lesson_content_id, records[i].source_quiz_content_id)
        if source_id is not None
    ]
    quiz_units = sorted(
        {q for i in no_quiz if (q := covering.get(records[i].module_unit_id)) is not None},
        key=str,
    )
    conditions: list[ColumnElement[bool]] = [GeneratedContent.id.in_(source_ids)]
    if quiz_units:
        conditions.append(
            and_(
                GeneratedContent.module_unit_id.in_(quiz_units),
                GeneratedContent.content_type == "quiz",
                GeneratedContent.language.in_(sorted({records[i].language for i in no_quiz})),
            )
        )
    rows = (
        await session.execute(
            select(
                GeneratedContent.id,
                GeneratedContent.content_revision,
                GeneratedContent.content,
                GeneratedContent.module_unit_id,
                GeneratedContent.content_type,
                GeneratedContent.language,
            ).where(or_(*conditions))
        )
    ).all()
    by_id = {row.id: row for row in rows}
    quizzes_by_unit = {
        (row.module_unit_id, row.language) for row in rows if row.content_type == "quiz"
    }

    for i in candidates:
        record = records[i]
        lesson = by_id.get(record.source_lesson_content_id)
        if not _lesson_unchanged(record, lesson, markers[i]):
            continue
        if expected is not None:
            # v4: told with this bible, within this plan, from this plan entry.
            want = expected.get(record.module_unit_id)
            marker = markers[i] if isinstance(markers[i], dict) else {}
            if want is None or any(marker.get(key) != value for key, value in want.items()):
                continue
        if record.source_quiz_revision is not None:
            quiz = by_id.get(record.source_quiz_content_id)
            # The lesson unit's own quiz is never a source now: rebuild from
            # the covering quiz.
            results[i] = (
                _source_unchanged(quiz, record.source_quiz_revision, record.source_quiz_digest)
                and quiz is not None
                and quiz.module_unit_id != record.module_unit_id
            )
            continue
        quiz_unit = covering.get(record.module_unit_id)
        results[i] = quiz_unit is None or (quiz_unit, record.language) not in quizzes_by_unit
    return results


async def story_sources_are_fresh(session: AsyncSession, record: StoryCourseRecord) -> bool:
    """Whether a story row can still be served as it is.

    * A hand-authored week (``module_id`` null) is never stale.
    * A chapter (``module_unit_id`` set) is fresh while its builder, lesson
      and covering quiz are unchanged (:func:`chapters_are_fresh`).
    * A module story must never be judged here: its freshness depends on its
      roster and every chapter
      (:func:`app.domain.services.story_module_service.module_story_is_fresh`),
      so it is reported stale.
    """
    if record.module_id is None:
        return True
    if record.module_unit_id is None:
        logger.warning(
            "A module story was checked as a chapter; use module_story_is_fresh",
            slug=record.slug,
        )
        return False
    return (await chapters_are_fresh(session, [record]))[0]


async def select_unit_content_row(
    session: AsyncSession,
    module_unit_id: uuid.UUID,
    content_type: str,
    language: str,
    level: int,
    country: str | None,
) -> GeneratedContent | None:
    """The unit's cached row for ``content_type``: exact level and country first.

    A story is cached per unit and language only, so any level or country of
    the lesson can seed it; the requested one is preferred, then the same
    level, then the newest.
    """
    rows = (
        (
            await session.execute(
                select(GeneratedContent)
                .where(
                    GeneratedContent.module_unit_id == module_unit_id,
                    GeneratedContent.content_type == content_type,
                    GeneratedContent.language == language,
                )
                .order_by(GeneratedContent.generated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    exact = [r for r in rows if r.level == level and r.country_context == country]
    same_level = [r for r in rows if r.level == level]
    return (exact or same_level or rows)[0]


# --------------------------------------------------------------------------
# Validation and the generation loop
# --------------------------------------------------------------------------


def validate_document(doc: dict[str, Any]) -> ValidationReport:
    """Appendix C plus the generator's question floor, never raising."""
    try:
        course = StoryCourse.model_validate(doc)
    except Exception as exc:  # pragma: no cover - the builder owns the shape
        return ValidationReport(
            ok=False,
            errors=[
                ValidationIssue(
                    severity="error",
                    code="malformed_course_file",
                    path="",
                    message=str(exc)[:500],
                )
            ],
        )
    return repair.publishable(validate_story_course(course, generated=True), doc)


def _parses(doc: dict[str, Any]) -> bool:
    try:
        StoryCourse.model_validate(doc)
    except Exception:
        return False
    return True


def _unbuildable_issue() -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code="malformed_spine",
        path="",
        message=(
            "the story could not be built from your previous JSON: a field has the wrong"
            " shape. Return exactly the structure asked for (lists as lists, texts as"
            ' {"en": ..., "fr": ...} objects)'
        ),
    )


def _empty_spine_issue() -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code="empty_spine",
        path="",
        message=(
            "nothing in your previous JSON could be used: return one JSON object with"
            " exactly the fields asked for at its top level"
        ),
    )


def _no_model_content_issue() -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code="no_model_content",
        path="",
        message=(
            "no answer of the model could be used, so this is only the lesson and quiz,"
            " untranslated; it is never published"
        ),
    )


def attempt_rank(report: ValidationReport, *, authored: bool = True) -> tuple[int, int, int, int]:
    """How far an attempt is from publishable, judged as it will be settled.

    It picks the draft when no attempt can be published; which valid result
    is published is :func:`outcome_rank`'s call.

    Lower is better. A build that carries no model content (``authored`` is
    false: an unreadable answer's, or one the builder could use nothing of)
    is never published, so it comes after every build that does, whatever
    its counts. Then errors other than copied translations, then the copied
    translations, then warnings. After the repair budget a copied translation
    is settled into a warning (:func:`repair.settle_translations`), so an
    attempt whose only errors are copies publishes and must beat one with any
    other error, however many copies it carries.
    """
    copies = sum(1 for issue in report.errors if issue.code in repair.SETTLEABLE)
    return (0 if authored else 1), len(report.errors) - copies, copies, len(report.warnings)


@dataclass
class _Attempt:
    """One model answer, built and validated (before copies are settled)."""

    number: int
    #: The answer as read; ``{}`` for an unreadable one.
    spine: dict[str, Any]
    build: repair.StoryBuild
    report: ValidationReport
    #: Whether the story holds anything of the answer's own (see :func:`attempt_rank`).
    authored: bool

    @property
    def order(self) -> tuple[tuple[int, int, int, int], int]:
        """Best first; on a tie, the earlier attempt."""
        return attempt_rank(self.report, authored=self.authored), self.number


@dataclass
class StoryGeneration:
    doc: dict[str, Any]
    report: ValidationReport
    model_calls: int
    salvaged: bool = False
    #: What the salvage pass dropped: ``questions``, ``exercises`` and
    #: ``minigames`` ids (a dropped mini-game is replaced by the built-in one).
    dropped: dict[str, list[str]] = field(default_factory=dict)
    #: The spine the stored document was built from (v4: its recap, props now).
    spine: dict[str, Any] = field(default_factory=dict)


#: The keys a practice pack writes (#2680), and those a chapter's story writes.
PACK_KEYS = ("objectives", "misconceptions", "derived", "questions", "exercises", "minigame")
STORY_KEYS = ("props", "scenes", "facts", "recap", "props_now")


@dataclass
class PackGeneration:
    """A chapter's practice pack (v4): what was read, and what still fails."""

    pack: dict[str, Any]
    issues: list[ValidationIssue]
    model_calls: int


def stub_scenes(ctx: repair.LessonStoryContext, pack: dict[str, Any]) -> list[dict[str, Any]]:
    """A scene made in code that asks every question of a pack, gives its task and game."""
    bible = ctx.bible_content
    place = next(iter(p["id"] for p in bible.get("places") or []), "classroom")
    line = {"type": "narrate", "en": "The story goes on.", "fr": "L'histoire continue."}
    steps: list[dict[str, Any]] = [dict(line)]
    refs = [r for r in ctx.assigned_refs]
    for number, question in enumerate(pack.get("questions") or [], start=1):
        raw_id = question.get("id") if isinstance(question, dict) else None
        refs.append(str(raw_id) if raw_id else f"x{number}")
    for ref in refs:
        steps += [
            {"type": "say", "who": "friend", "mood": "talk", "en": "Your turn.", "fr": "À toi."},
            {"type": "ask", "ref": ref},
        ]
    for number, _exercise in enumerate(pack.get("exercises") or [], start=1):
        steps += [dict(line), {"type": "photo", "ref": f"E{number}"}]
    if ctx.has_game:
        steps += [dict(line), {"type": "game"}]
    steps.append(dict(line))
    return [{"place": place, "cast": ["hero", "friend"], "steps": steps}]


def pack_issues(ctx: repair.LessonStoryContext, pack: dict[str, Any]) -> list[ValidationIssue]:
    """What is wrong with a practice pack, on its own paths only.

    The pack is built around :func:`stub_scenes` through the chapter builder
    and validated; issues on the story's paths are left out (the stub has no
    story). Plus the pack's own codes: an assigned course question without
    a derived entry, a question on an IDEA the lesson does not have, an IDEA
    no question tests.
    """
    from app.ai.prompts.story_from_lesson import PACK_PATH_RE

    spine = {**pack, "scenes": stub_scenes(ctx, pack)}
    try:
        build = repair.build_story_document(ctx, spine, story_checks=False)
        report = repair.with_generator_issues(validate_document(build.doc), build)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:  # a pack the builder cannot read at all
        return [
            ValidationIssue(
                severity="error",
                code="malformed_spine",
                path="",
                message=f"the practice items could not be read: {type(exc).__name__}",
            )
        ]
    issues = [
        i for i in report.errors if PACK_PATH_RE.match(i.path) and i.code not in repair.STORY_CODES
    ]
    derived = {str(d.get("ref")): d for d in pack.get("derived") or [] if isinstance(d, dict)}
    for ref in ctx.assigned_refs:
        if ref not in derived:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="assigned_ref_missing",
                    path="derived",
                    message=f'write a "derived" entry for {ref}: it is assigned to this chapter',
                )
            )
    if not ctx.is_rally:
        ideas = len(ctx.lesson_list("concepts"))
        tested: set[int] = set()
        items = [(f"derived[{ref}]", d) for ref, d in derived.items()] + [
            (f"questions[{q.get('id') or n}]", q)
            for n, q in enumerate(pack.get("questions") or [], start=1)
            if isinstance(q, dict)
        ]
        for path, item in items:
            idea = item.get("idea")
            if not isinstance(idea, int) or isinstance(idea, bool) or not 1 <= idea <= ideas:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="question_off_idea",
                        path=f"{path}.idea",
                        message=f'"idea" is the IDEA number it tests, 1 to {ideas}',
                    )
                )
            else:
                tested.add(idea)
        missing = [n for n in range(1, ideas + 1) if n not in tested]
        if missing:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="idea_without_question",
                    path="questions",
                    message=f"IDEA {', '.join(map(str, missing))} has no question: write one",
                )
            )
    return issues


def outcome_rank(generation: StoryGeneration) -> tuple[int, int, int]:
    """How good a valid result is — settled, and salvaged if need be. Lower is better.

    Copied translations first: each is a line the learner reads in the wrong
    language. Then the items the salvage pass dropped: model-authored
    questions, exercises or the mini-game the story lost. Then the
    validator's other warnings. So a clean salvage of a real attempt beats an
    answer that is valid only once its copies are settled (a fragment, or a
    spine written in the target language alone), and an attempt the model
    repaired beats salvaging the one before it.
    """
    warnings = generation.report.warnings
    copies = sum(1 for issue in warnings if issue.code in repair.SETTLEABLE)
    dropped = sum(len(ids) for ids in generation.dropped.values())
    return copies, dropped, len(warnings) - copies


def build_context(
    module: Module,
    unit: ModuleUnit,
    language: str,
    lesson_content: dict[str, Any],
    quiz_row: GeneratedContent | None,
    quiz_unit: Any | None = None,
    *,
    bible: StoryBible | None = None,
    arc: str = repair.ARC_CONTINUES,
    country: str = "",
) -> repair.LessonStoryContext:
    """Everything the deterministic layer needs, read once from the ORM rows.

    ``quiz_unit`` is the covering quiz unit ``quiz_row`` belongs to; its MCQs
    are candidates the model picks from. ``None`` (a quiz scoped to the unit
    itself, every MCQ a question) is kept for direct callers: the pipeline
    never reads a lesson unit's own quiz any more. ``bible`` is the course's
    (the audience's default when ``None``) and ``arc`` the chapter's part in
    the module's mission.
    """
    from app.ai.prompts.audience import detect_audience

    def pair(en: str | None, fr: str | None) -> dict[str, str]:
        en, fr = (en or "").strip(), (fr or "").strip()
        return {"en": en or fr, "fr": fr or en}

    course = module.course
    mcqs: list[repair.QuizMcq] = []
    if quiz_row is not None:
        mcqs, _dropped = repair.parse_quiz_mcqs((quiz_row.content or {}).get("questions"))
    is_kids = detect_audience(course).is_kids
    bible = bible or default_bible(is_kids)
    return repair.LessonStoryContext(
        module_unit_id=unit.id,
        language=language,
        unit_number=unit.unit_number,
        unit_title=pair(unit.title_en, unit.title_fr),
        module_title=pair(module.title_en, module.title_fr),
        course_title=pair(course.title_en, course.title_fr) if course else pair("", ""),
        module_number=module.module_number or 1,
        lesson=dict(lesson_content or {}),
        mcqs=mcqs,
        has_quiz=bool(mcqs),
        is_kids=is_kids,
        quiz_scope="covering" if quiz_unit is not None else "unit",
        quiz_unit_number=str(quiz_unit.unit_number) if quiz_unit is not None else None,
        bible=bible.content,
        mission=mission_for(
            bible.content,
            module.id,
            module.module_number,
            pair(module.title_en, module.title_fr),
        ),
        arc=arc,
        country=country,
    )


class StoryFromLessonService:
    """Generates and caches one lesson unit's story: a chapter of its module story."""

    def __init__(
        self,
        claude_service: Any,
        lesson_service: Any | None = None,
        max_repair_calls: int = MAX_REPAIR_CALLS,
    ) -> None:
        self.claude_service = claude_service
        self.lesson_service = lesson_service
        self.max_repair_calls = max_repair_calls

    # -- the model ---------------------------------------------------------

    async def _call_model(
        self, system_prompt: str, user_message: str, *, kind: str = "story"
    ) -> dict[str, Any] | None:
        """One spine call — exactly one paid provider call; ``None`` when unreadable.

        ``max_retries=0`` turns off the service's own strict-JSON retry: an
        unreadable answer is an attempt of the repair loop, which re-asks with
        its own notice. Left on, every attempt could pay twice, and the task's
        time limit (sized for 1 + :data:`MAX_REPAIR_CALLS` calls) would not hold.

        #2702: the call writes at most the ``max_tokens`` of its ``kind`` and
        runs under its timeout (:func:`story_calls.structured_call`). An answer
        cut at that limit raises :class:`TruncatedResponse` — never a repair at
        the same budget — and a timeout :class:`StoryCallTimeout`.
        """
        from app.domain.services.story_calls import TruncatedResponse, structured_call

        try:
            spine = await structured_call(
                self.claude_service, system_prompt, user_message, kind=kind
            )
        except TruncatedResponse:
            raise
        except ValueError as exc:
            # generate_structured_content raises ValueError for a truncated,
            # unparseable answer; it is worth a repair call, not a crash.
            logger.warning("Story spine unusable", error=str(exc))
            return None
        if not isinstance(spine, dict) or spine.get("raw_response"):
            logger.warning("Story spine was not valid JSON")
            return None
        if spine.pop("__complete", None) is not True:
            logger.warning("Story spine lacks the __complete sentinel (possibly truncated)")
        return spine

    async def generate_story(
        self,
        ctx: repair.LessonStoryContext,
        pack: dict[str, Any],
        *,
        system_prompt: str,
        max_repair_calls: int = repair.STORY_REPAIR_CALLS,
    ) -> StoryGeneration:
        """v4 (#2680): one chapter's story, told from the plan around its practice pack.

        The model writes only the story (props, scenes, recap, props now,
        facts); the spine the builder reads is the pack with those keys and
        the plan's story title. A repair re-asks for the story JSON only.
        """
        from app.ai.prompts.story_from_lesson import (
            build_chapter_story_message,
            build_rally_story_message,
            build_story_repair_message,
        )

        message = (
            build_rally_story_message(ctx, pack)
            if ctx.is_rally
            else build_chapter_story_message(ctx, pack)
        )
        title = (ctx.plan_entry or {}).get("title")

        def merge(answer: dict[str, Any]) -> dict[str, Any]:
            spine = {key: value for key, value in pack.items() if key in PACK_KEYS}
            for key in STORY_KEYS:
                if key in answer:
                    spine[key] = answer[key]
            if title:
                spine["chapter_title"] = title
            return spine

        return await self.generate_document(
            ctx,
            system_prompt=system_prompt,
            user_message=message,
            repair_message=build_story_repair_message,
            merge=merge,
            max_repair_calls=max_repair_calls,
            kind="rally" if ctx.is_rally else "story",
        )

    async def generate_pack(
        self,
        ctx: repair.LessonStoryContext,
        *,
        system_prompt: str,
        max_repair_calls: int = repair.PACK_REPAIR_CALLS,
    ) -> PackGeneration:
        """v4 (#2680): the practice items of a chapter, written apart from its story.

        Checked by building them around a stub scene made in code and keeping
        only the issues on the pack's own paths (:func:`pack_issues`); at most
        ``max_repair_calls`` repairs. The best pack read is returned, issues
        and all: what still fails is settled or salvaged with the story.
        """
        from app.ai.prompts.story_from_lesson import build_pack_message, build_pack_repair_message
        from app.domain.services.story_calls import StoryCallTimeout, TruncatedResponse, concise

        message = build_pack_message(ctx)
        budget = 1 + max_repair_calls
        best: tuple[int, dict[str, Any], list[ValidationIssue]] | None = None
        issues: list[ValidationIssue] = []
        previous: dict[str, Any] | None = None
        calls = 0
        truncated = 0
        concise_next = False
        with ai_usage_context(FEATURE_STORY_GENERATION, only_if_unset=True):
            for number in range(budget):
                if concise_next:
                    # The one retry of an answer cut at max_tokens (#2702): the
                    # same request, concise — never a repair of the cut answer.
                    prompt, concise_next = concise(message), False
                else:
                    prompt = (
                        message
                        if number == 0
                        else build_pack_repair_message(message, issues, previous, number, budget)
                    )
                calls += 1
                try:
                    answer = await self._call_model(system_prompt, prompt, kind="pack")
                except (SoftTimeLimitExceeded, StoryCallTimeout):
                    raise
                except TruncatedResponse:
                    truncated += 1
                    if truncated == 1:
                        concise_next = True
                        continue
                    # Cut twice: no more calls at this budget (#2702).
                    if best is None:
                        raise
                    break
                except Exception as exc:
                    if best is None:
                        raise
                    # A repair the provider could not answer: the paid pack read stays.
                    logger.warning("Story pack repair failed; best pack kept", error=str(exc))
                    break
                if answer is None:
                    issues, previous = [], None
                    continue
                pack = {key: value for key, value in answer.items() if key in PACK_KEYS}
                issues = pack_issues(ctx, pack)
                if best is None or len(issues) < best[0]:
                    best = (len(issues), pack, issues)
                if not issues:
                    break
                previous = answer
        pack, left = (best[1], best[2]) if best is not None else ({}, [])
        logger.info(
            "Story practice pack made",
            slug=ctx.slug,
            calls=calls,
            issues=sorted({i.code for i in left}),
        )
        return PackGeneration(pack=pack, issues=left, model_calls=calls)

    async def generate_document(
        self,
        ctx: repair.LessonStoryContext,
        *,
        system_prompt: str,
        user_message: str | None = None,
        repair_message: Any = None,
        merge: Any = None,
        max_repair_calls: int | None = None,
        kind: str = "story",
    ) -> StoryGeneration:
        """Spine call → deterministic build → validate → bounded repair → salvage.

        Database-free, so the whole pipeline can be tested with a fake model.
        The loop stops at the first attempt that is valid as it stands and
        carries model content; :meth:`_choose` then picks what is stored, with
        the validator's ``checks`` written into it. Never raises for a bad
        spine: a spine the builder chokes on counts as an unreadable attempt,
        and when no attempt could be built at all the result is an
        unpublishable placeholder whose report carries ``malformed_course_file``.
        """
        from app.ai.prompts.story_from_lesson import (
            build_repair_message,
            build_story_user_message,
        )

        user_message = user_message or build_story_user_message(ctx)
        repair_message = repair_message or build_repair_message
        repairs = self.max_repair_calls if max_repair_calls is None else max_repair_calls
        budget = 1 + repairs
        attempts: list[_Attempt] = []
        empty_doc: dict[str, Any] | None = None
        feedback_spine: dict[str, Any] | None = None
        issues: list[ValidationIssue] = []
        calls = 0
        truncated = 0

        from app.domain.services.story_calls import TruncatedResponse, concise

        with ai_usage_context(FEATURE_STORY_GENERATION, only_if_unset=True):
            for number in range(budget):
                if truncated == 1:
                    # The one retry of an answer cut at max_tokens (#2702): the
                    # same request, concise — never a repair of the cut answer.
                    message = concise(user_message)
                else:
                    message = (
                        user_message
                        if number == 0
                        else repair_message(user_message, issues, feedback_spine, number, budget)
                    )
                calls += 1
                try:
                    answer = await self._call_model(system_prompt, message, kind=kind)
                except TruncatedResponse as exc:
                    truncated += 1
                    logger.warning(
                        "Story answer cut at max_tokens",
                        slug=ctx.slug,
                        attempt=number + 1,
                        output_tokens=exc.output_tokens,
                        length=exc.length,
                    )
                    if truncated == 1:
                        continue
                    break  # cut twice: this chapter's calls end here
                if truncated == 1:
                    truncated = 2  # the retry was read: no second concise retry
                # The model's own JSON goes back in a repair; the builder reads
                # it merged into the spine (v4: around the practice pack).
                spine = merge(answer) if merge is not None and answer is not None else answer
                attempted = self._build_and_validate(ctx, spine or {})
                if attempted is None:
                    if spine is None:
                        # Not JSON (the builder failing on no answer is its
                        # own bug): ask again for readable JSON.
                        issues = []
                    else:
                        # The spine was JSON but not a shape the builder can use.
                        feedback_spine, issues = answer, [_unbuildable_issue()]
                    continue
                build, report = attempted
                authored = False
                if spine is not None:
                    # An answer the builder used nothing of builds the same
                    # story as no answer at all: the lesson and quiz alone.
                    if empty_doc is None:
                        empty_doc = self._empty_doc(ctx)
                    authored = build.doc != empty_doc
                attempts.append(_Attempt(number, spine or {}, build, report, authored))
                logger.info(
                    "Story attempt validated",
                    slug=ctx.slug,
                    attempt=number + 1,
                    readable=spine is not None,
                    authored=authored,
                    errors=len(report.errors),
                    warnings=len(report.warnings),
                )
                if report.ok and authored:
                    break
                if spine is None:
                    issues = []
                elif not authored:
                    feedback_spine, issues = answer, [_empty_spine_issue()]
                else:
                    feedback_spine, issues = answer, repair.repair_issues(report)

        generation = self._choose(ctx, attempts, empty_doc)
        generation.model_calls = calls
        if not _parses(generation.doc):
            # Only a builder bug gets here; store the bare header as a draft
            # (the report already says malformed_course_file) rather than fail.
            generation.doc = repair.minimal_document(ctx)

        generation.doc["checks"] = generation.report.checks.model_dump(mode="json")
        logger.info(
            "Story generated",
            slug=ctx.slug,
            ok=generation.report.ok,
            errors=len(generation.report.errors),
            warnings=len(generation.report.warnings),
            model_calls=calls,
            salvaged=generation.salvaged,
        )
        return generation

    @staticmethod
    def _build_and_validate(
        ctx: repair.LessonStoryContext,
        spine: dict[str, Any],
        **drops: Any,
    ) -> tuple[repair.StoryBuild, ValidationReport] | None:
        """Build and validate one spine; ``None`` when the builder raised.

        The builder is defensive about every shape it reads, but one missed
        shape must cost an attempt, not the task: an exception here would store
        nothing, and every later view would pay for a new generation. A Celery
        time limit is not a bad spine and is never swallowed.
        """
        try:
            build = repair.build_story_document(ctx, spine, **drops)
            report = repair.with_generator_issues(validate_document(build.doc), build)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            logger.warning(
                "Story could not be built from the spine",
                slug=ctx.slug,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            return None
        return build, report

    def _empty_doc(self, ctx: repair.LessonStoryContext) -> dict[str, Any] | None:
        """The story built from no answer at all; ``None`` if even that fails."""
        attempted = self._build_and_validate(ctx, {})
        return attempted[0].doc if attempted is not None else None

    def _choose(
        self,
        ctx: repair.LessonStoryContext,
        attempts: list[_Attempt],
        empty_doc: dict[str, Any] | None,
    ) -> StoryGeneration:
        """What is stored: the best result that can be published, else a draft.

        Every attempt carrying model content is settled (copied translations
        become warnings) and, if anything else still fails, salvaged. Of those
        that come out valid, the best by :func:`outcome_rank` is stored — the
        earlier attempt on a tie — so an answer that is valid only on copies
        never beats a clean salvage of a real attempt. If none comes out
        valid, the best attempt (:attr:`_Attempt.order`) is stored as a draft,
        as settled. A build without model content — the lesson and quiz alone,
        untranslated — is never published: it is the draft only when no
        attempt carries any, and its report then says so.
        """
        if not attempts:
            return self._unbuildable(ctx)
        valid: list[tuple[tuple[int, int, int], int, StoryGeneration]] = []
        for attempt in attempts:
            if attempt.authored:
                result = self._as_published(ctx, attempt, empty_doc)
                if result is not None:
                    valid.append((outcome_rank(result), attempt.number, result))
        if valid:
            rank, number, chosen = min(valid, key=lambda item: item[:2])
            logger.info(
                "Story attempt chosen",
                slug=ctx.slug,
                attempt=number + 1,
                copies=rank[0],
                dropped=rank[1],
                salvaged=chosen.salvaged,
            )
            return chosen
        best = min(attempts, key=lambda attempt: attempt.order)
        report = repair.settle_translations(best.report)
        if not best.authored:
            report = repair.with_issues(report, [_no_model_content_issue()])
        return StoryGeneration(doc=best.build.doc, report=report, model_calls=0, spine=best.spine)

    def _as_published(
        self,
        ctx: repair.LessonStoryContext,
        attempt: _Attempt,
        empty_doc: dict[str, Any] | None,
    ) -> StoryGeneration | None:
        """``attempt`` as it would be published — settled, else salvaged — or ``None``.

        A salvage that leaves nothing of the answer (the empty build) is not a
        result.
        """
        report = repair.settle_translations(attempt.report)
        if report.ok:
            result: StoryGeneration | None = StoryGeneration(
                doc=attempt.build.doc, report=report, model_calls=0
            )
        else:
            result = self._salvage(ctx, attempt.spine, attempt.build, report)
            if result is None or result.doc == empty_doc:
                return None
        result.spine = attempt.spine
        return self._with_fallback_cards(ctx, attempt.spine, result)

    def _with_fallback_cards(
        self, ctx: repair.LessonStoryContext, spine: dict[str, Any], result: StoryGeneration
    ) -> StoryGeneration:
        """``result`` with a card from the lesson for each concept it never taught.

        Once the repair budget is spent a missed concept is only a warning, but
        the chapter completes its lesson unit: the learner must see every
        concept, so the lesson's own text stands in for the missing card.
        """
        if not any(w.code == repair.CONCEPT_NOT_COVERED for w in result.report.warnings):
            return result
        dropped = result.dropped
        attempted = self._build_and_validate(
            ctx,
            spine,
            drop_question_ids=dropped.get("questions", []),
            drop_exercise_ids=dropped.get("exercises", []),
            drop_minigame=bool(dropped.get("minigames")),
            cover_missing_concepts=True,
        )
        if attempted is None:
            return result
        build, report = attempted
        report = repair.settle_translations(report)
        if not report.ok:
            return result
        return StoryGeneration(
            doc=build.doc,
            report=report,
            model_calls=0,
            salvaged=result.salvaged,
            dropped=dict(dropped),
            spine=spine,
        )

    def _unbuildable(self, ctx: repair.LessonStoryContext) -> StoryGeneration:
        """The draft stored when no attempt could be built; it is never served.

        Like any story that could not be made valid, it is not regenerated on
        the next view (the API answers 409): only when its lesson or quiz
        changes, or when an admin forces it.
        """
        attempted = self._build_and_validate(ctx, {})
        doc = attempted[0].doc if attempted is not None else repair.minimal_document(ctx)
        issue = ValidationIssue(
            severity="error",
            code="malformed_course_file",
            path="",
            message="no answer of the model could be built into a story",
        )
        report = ValidationReport(ok=False, errors=[issue])
        report = report.model_copy(
            update={"checks": report.checks.model_copy(update={"errors": 1})}
        )
        return StoryGeneration(doc=doc, report=report, model_calls=0)

    def _salvage(
        self,
        ctx: repair.LessonStoryContext,
        spine: dict[str, Any],
        build: repair.StoryBuild,
        report: ValidationReport,
    ) -> StoryGeneration | None:
        """Drop the questions, exercises or mini-game that still fail, once.

        Accepted only if the result is clean and keeps at least half of the
        questions — a story that lost most of the unit's quiz is not the
        unit's story.
        """
        questions, exercises, minigame = repair.implicated_items(report)
        if not (questions or exercises or minigame):
            return None
        attempted = self._build_and_validate(
            ctx,
            spine,
            drop_question_ids=questions,
            drop_exercise_ids=exercises,
            drop_minigame=minigame,
        )
        if attempted is None:
            return None
        rebuilt, rebuilt_report = attempted
        rebuilt_report = repair.settle_translations(rebuilt_report)
        before = len(build.doc["questions"])
        after = len(rebuilt.doc["questions"])
        if not rebuilt_report.ok or after < max(repair.MIN_QUESTIONS, math.ceil(before / 2)):
            return None
        logger.warning(
            "Story salvaged by dropping items that kept failing",
            slug=ctx.slug,
            questions=sorted(questions),
            exercises=sorted(exercises),
            minigame=minigame,
        )
        return StoryGeneration(
            doc=rebuilt.doc,
            report=rebuilt_report,
            model_calls=0,
            salvaged=True,
            dropped={
                "questions": sorted(questions),
                "exercises": sorted(exercises),
                "minigames": [repair.MINIGAME_ID] if minigame else [],
            },
        )

    # -- the database --------------------------------------------------------

    async def _lesson_row(
        self,
        session: AsyncSession,
        module: Module,
        unit: ModuleUnit,
        language: str,
        level: int,
        country: str,
    ) -> GeneratedContent:
        if not is_lesson_unit(unit.unit_type):
            # Never generate a lesson for a quiz, case-study or scenario unit:
            # it would be an orphan nobody reads, paid for.
            raise NotALessonUnit(f"Unit {unit.unit_number} is a {unit.unit_type} unit")
        row = await select_unit_content_row(session, unit.id, "lesson", language, level, country)
        if row is not None:
            return row
        if self.lesson_service is None:
            raise ValueError(f"No lesson is cached for unit {unit.unit_number} ({language})")
        with ai_usage_context(FEATURE_LESSON_GENERATION):
            lesson = await self.lesson_service.get_or_generate_lesson(
                module_id=module.id,
                unit_id=unit.unit_number,
                language=language,
                country=country,
                level=level,
                session=session,
            )
        row = await session.get(GeneratedContent, lesson.id)
        if row is None:
            row = await select_unit_content_row(
                session, unit.id, "lesson", language, level, country
            )
        if row is None:
            raise ValueError(f"Lesson for unit {unit.unit_number} could not be generated")
        return row

    async def get_or_generate_unit_story(
        self,
        module_id: uuid.UUID,
        unit_id: str,
        language: str,
        session: AsyncSession,
        *,
        level: int = 1,
        country: str = "CI",
        force_regenerate: bool = False,
        bible: StoryBible | None = None,
        arc: str | None = None,
    ) -> StoryCourseRecord:
        """Return the unit's chapter, generating and caching it when needed.

        A cached chapter is returned as-is while it is fresh — valid or not,
        so a chapter that could not be made valid is not regenerated (and paid
        for) on every view; it is retried when the lesson or quiz changes, when
        the generator, the course bible or the chapter's part in the module's
        mission changes, or when an admin forces it.

        ``bible`` and ``arc`` are given by the module story, which makes the
        bible first. Without a bible, the course's stored one (else the
        audience's default) is used; without an arc, the cached chapter's own
        is accepted and a new one is told as a middle chapter.

        Raises :class:`NotALessonUnit` for a quiz, case-study or scenario unit
        before anything is generated.
        """
        from app.ai.prompts.story_from_lesson import get_story_system_prompt

        module = (
            await session.execute(
                select(Module).options(selectinload(Module.course)).where(Module.id == module_id)
            )
        ).scalar_one_or_none()
        if module is None:
            raise ValueError(f"Module {module_id} not found")
        unit = (
            await session.execute(
                select(ModuleUnit).where(
                    ModuleUnit.module_id == module_id, ModuleUnit.unit_number == unit_id
                )
            )
        ).scalar_one_or_none()
        if unit is None:
            raise ValueError(f"Unit {unit_id} not found in module {module_id}")
        if not is_lesson_unit(unit.unit_type):
            raise NotALessonUnit(f"Unit {unit_id} is a {unit.unit_type} unit, not a lesson")

        if bible is None:
            bible = await self._stored_bible(session, module)

        existing = await find_unit_story(session, unit.id, language)
        if (
            existing is not None
            and not force_regenerate
            and chapter_marker_matches(
                (existing.content or {}).get("sira_chapter"), bible.digest, arc
            )
            and await story_sources_are_fresh(session, existing)
        ):
            return existing
        arc = arc or repair.ARC_CONTINUES

        lesson_row = await self._lesson_row(session, module, unit, language, level, country)
        quiz_row, quiz_unit = await self._quiz_source(session, unit, language, lesson_row)
        ctx = build_context(
            module,
            unit,
            language,
            lesson_row.content or {},
            quiz_row,
            quiz_unit,
            bible=bible,
            arc=arc,
            country=lesson_row.country_context or country,
        )

        course = module.course

        def in_target(en: str | None, fr: str | None) -> str | None:
            return fr if language == "fr" else en

        system_prompt = get_story_system_prompt(
            language=language,
            country=lesson_row.country_context or country,
            level=lesson_row.level,
            bloom_level=module.bloom_level or "",
            course_title=in_target(course.title_en, course.title_fr) if course else None,
            course_description=(
                in_target(course.description_en, course.description_fr) if course else None
            ),
            module_title=ctx.module_title[language],
            unit_title=ctx.unit_title[language],
            course=course,
        )
        with ai_usage_context(
            FEATURE_STORY_GENERATION,
            module_id=module.id,
            course_id=module.course_id,
        ):
            generation = await self.generate_document(ctx, system_prompt=system_prompt)

        binding = StoryBinding(
            module_id=module.id,
            module_unit_id=unit.id,
            language=language,
            lesson_content_id=lesson_row.id,
            lesson_revision=lesson_row.content_revision or 1,
            quiz_content_id=quiz_row.id if quiz_row is not None else None,
            quiz_revision=(quiz_row.content_revision or 1) if quiz_row is not None else None,
            lesson_digest=content_digest(lesson_row.content),
            quiz_digest=content_digest(quiz_row.content) if quiz_row is not None else None,
        )
        return await self._persist(session, generation, binding, module.course_id)

    @staticmethod
    async def _stored_bible(session: AsyncSession, module: Module) -> StoryBible:
        """The course's stored bible, else the audience's default (never written here)."""
        from app.ai.prompts.audience import detect_audience

        row = await find_bible(session, module.course_id) if module.course_id else None
        if row is not None:
            return StoryBible(content=row.content, digest=row.digest)
        return default_bible(detect_audience(module.course).is_kids)

    async def _quiz_source(
        self,
        session: AsyncSession,
        unit: ModuleUnit,
        language: str,
        lesson_row: GeneratedContent,
    ) -> tuple[GeneratedContent | None, Any | None]:
        """``(quiz row, covering quiz unit)`` the chapter's questions come from.

        Only the cached quiz of the module's quiz unit that covers the lesson
        (:func:`covering_quiz_unit`, contract C-1): its MCQs are candidates the
        model picks from, at most :data:`story_repair.MAX_PICKED_MCQS`, copied
        verbatim. The lesson unit's own quiz — an offline download creates one
        for every unit — is never used: under the old rule one learner's
        download made the story stale for everyone, and paid for again.
        ``(None, None)`` when there is no covering quiz unit or it has no
        cached quiz in ``language``: every question is then model-authored.
        No quiz is generated here; the module story task generates a missing
        covering quiz before it asks for the chapter.

        Level and country follow the lesson row the story is built from.
        """
        level, country = lesson_row.level, lesson_row.country_context
        quiz_unit = await find_covering_quiz_unit(session, unit.id)
        if quiz_unit is None:
            return None, None
        covering = await select_unit_content_row(
            session, quiz_unit.id, "quiz", language, level, country
        )
        if covering is None:
            return None, None
        return covering, quiz_unit

    async def _persist(
        self,
        session: AsyncSession,
        generation: StoryGeneration,
        binding: StoryBinding,
        course_id: uuid.UUID | None,
    ) -> StoryCourseRecord:
        course = StoryCourse.model_validate(generation.doc)
        for attempt in range(2):
            try:
                record = await upsert_story_course(
                    session,
                    course=course,
                    content=generation.doc,
                    report=generation.report,
                    course_id=course_id,
                    publish=generation.report.ok,
                    binding=binding,
                )
                await session.commit()
                await session.refresh(record)
                break
            except IntegrityError:
                # Another worker stored the same unit story first; update it.
                await session.rollback()
                if attempt:
                    raise
        logger.info(
            "Lesson story stored",
            slug=record.slug,
            status=record.status,
            is_valid=record.is_valid,
            max_points=record.max_points,
        )
        return record
