"""One story per module: planned, told chapter by chapter, joined (contract C-3, #2680).

A module story is one ``story-course/1`` week per ``(module, language)``,
stored in ``story_courses`` with ``module_id`` set and no unit (migration
107). A module is ONE episode: one chapter per **lesson** unit, in teaching
order, each opening where the previous one ended, then — when the module has
a quiz unit — the **rally**, the climax. It is told by the course's
characters in the course's places, the **course bible** (:mod:`story_bible`,
migration 108), which is never changed here: the course's art is keyed on it.

Story generator v4 ("plan, then tell"), run by
:meth:`ModuleStoryService.get_or_generate_module_story` inside
:func:`app.tasks.content_generation.generate_module_story_task`:

0. **Prep**, concurrently: the course's bible (made once per course) while
   every lesson unit's lesson and every covering quiz is made if missing.
   Each lesson's **fact sheet** (its ideas, key points and figures — never its
   introduction, field example or synthesis) and the **name blocklist** (the
   people and towns of the lessons' own examples) are built in code.
1. **The episode plan** (:mod:`story_plan`, one call and at most one repair):
   premise, voices, catchphrases, props, and per chapter its beats, hook and
   course questions; then the rally. Cached in ``story_module_plans``.
2. **Practice packs**, concurrently (at most ``concurrency`` at a time): each
   chapter's questions, paper task and game, written apart from its story.
   Each is kept with the plan the moment it is made (:func:`story_plan.save_pack`),
   so a run that stops — a deadline, a failed chapter — never pays for it again.
3. **The chapters, in order**: each told from the plan, the story so far and
   the previous chapter's real last scene (``WHERE THE LAST CHAPTER
   STOPPED``). A chapter that fails does not stop the others: the next one
   opens on the plan's OPENS ON, and :class:`ChapterGenerationFailed` is
   raised at the end — the module row is not written, the chapters made stay
   cached, and the next run tells only the failed one, with both its
   neighbours' scenes. A chapter that cannot be made valid twice with the
   same inputs is kept as a draft (its unit shows the "still being written"
   placeholder) rather than paid for on every open.
4. **The rally** from every chapter's recap and cards, cached in the module
   row's manifest with a digest of its inputs.
5. **Assembly** (:mod:`story_module_assembly`, no model).

Before each story call the run checks its deadline; with less than
:data:`STORY_CALL_RESERVE_S` left it stops cleanly
(:class:`StoryDeadlineReached`) and the task dispatches a continuation:
chapters are cached one by one, so nothing is paid for twice.

Freshness (:func:`module_story_is_fresh`) needs no model and five queries
however many chapters there are: the roster, the course bible's digest, the
plan's digests, the chapter rows, and one query of every chapter's sources —
plus, with a rally, one of the quiz rows it was made from. A chapter is
fresh while it was built by this builder, with this bible, within this plan
(its global digest), from this plan entry (its beat digest), and its
lesson's fact sheet and quiz row are unchanged. A module story is stale when
the assembler or generator version, the bible, the plan, the roster or any
chapter row (id and ``updated_at``) differs from its manifest. A module story
the assembler could not make valid is merged again once; after that it
counts as current, so the API answers 409 instead of looping.
"""

from __future__ import annotations

import asyncio
import copy
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

import structlog
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, selectinload

from app.ai.usage_context import ai_usage_context
from app.api.v1.schemas.story_course import StoryCourse
from app.domain.models.ai_usage_event import (
    FEATURE_LESSON_GENERATION,
    FEATURE_QUIZ_GENERATION,
    FEATURE_STORY_GENERATION,
)
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services import story_repair as repair
from app.domain.services.story_bible import (
    DEFAULTED,
    BibleModule,
    StoryBible,
    StoryBibleService,
    default_bible,
    find_bible,
    find_bible_digest,
    mission_for,
)
from app.domain.services.story_from_lesson_service import (
    MAX_REPAIR_CALLS,
    ModuleStoryBinding,
    StoryBinding,
    StoryFromLessonService,
    _unit_order,
    chapters_are_fresh,
    content_digest,
    covering_quiz_units,
    select_unit_content_row,
    upsert_story_course,
)
from app.domain.services.story_module_assembly import (
    MODULE_ASSEMBLER_VERSION,
    ChapterSource,
    ModuleStoryContext,
    StoryUnit,
    assemble_module_story,
    module_story_slug,
    unit_role,
    validate_module_story,
)
from app.domain.services.story_plan import (
    EpisodePlan,
    PlanCandidate,
    PlanLesson,
    PlanRequest,
    StoryPlanService,
    entry_refs,
    find_plan,
    find_plan_digests,
    mcq_key,
    save_pack,
    sha,
    stored_packs,
)
from app.domain.services.story_props import plan_props
from app.domain.services.story_stems import STEM_JUDGE_VERSION, approve_stems, approved_stems

logger = structlog.get_logger(__name__)

#: Lessons, quizzes and packs made at the same time, each with its own session.
DEFAULT_CONCURRENCY = 6

#: Extra model calls of the rally's story after its first one.
RALLY_REPAIR_CALLS = repair.STORY_REPAIR_CALLS

#: A chapter that could not be made valid this many times with the same
#: inputs is kept as a draft (its unit shows the placeholder) until they change.
CHAPTER_FAILURE_CAP = 2
#: A module story the assembler could not make valid is merged again this
#: many times in all; after that the draft counts as current (409).
ASSEMBLY_FAILURE_CAP = 2
#: A story call is not started with less time than this left before the deadline.
STORY_CALL_RESERVE_S = 240.0


def story_dispatch_key(module_id: uuid.UUID, language: str) -> str:
    """Redis key holding the id of the task generating a module's story in ``language``."""
    return f"story_dispatch:module:{module_id}:{language}"


class NoStoryContent(ValueError):
    """The module has no lesson unit, so there is nothing to tell."""


class ChapterGenerationFailed(Exception):
    """Some chapters could not be made; the module story was not written.

    ``failed_units`` are their unit numbers, in teaching order. The chapters
    that were made are cached, so the next attempt makes only these.
    """

    def __init__(self, failed_units: list[str], errors: dict[str, str] | None = None) -> None:
        super().__init__(f"Story chapters failed for units {', '.join(failed_units)}")
        self.failed_units = failed_units
        self.errors = dict(errors or {})


class StoryDeadlineReached(Exception):
    """The run stopped before a story call it had no time left for.

    Every chapter told so far is cached; the task dispatches a continuation.
    """

    def __init__(self, told: list[str]) -> None:
        super().__init__(f"Story deadline reached after {', '.join(told) or 'no chapter'}")
        self.told = told


class CoveringQuizUnavailable(RuntimeError):
    """The quiz of the quiz unit covering a lesson could not be generated."""


class ModuleStoryAssemblyFailed(RuntimeError):
    """The assembled module story does not even parse: an assembler bug."""


def mission_arcs(units: Sequence[StoryUnit]) -> dict[uuid.UUID, str]:
    """Each lesson unit's part in the module's mission (``story_repair.ARC_*``).

    The v3 arc; a chapter told without a plan (direct callers) still uses it.
    """
    lessons = [u for u in units if u.role == "lesson"]
    has_rally = any(u.role == "quiz_checkpoint" for u in units)
    return {
        unit.module_unit_id: repair.mission_arc(index, len(lessons), has_rally=has_rally)
        for index, unit in enumerate(lessons)
    }


# --------------------------------------------------------------------------
# The roster
# --------------------------------------------------------------------------


def _pair(en: str | None, fr: str | None) -> dict[str, str]:
    en, fr = (en or "").strip(), (fr or "").strip()
    return {"en": en or fr, "fr": fr or en}


class _RosterUnit(NamedTuple):
    """A unit as :func:`covering_quiz_unit` reads it."""

    id: uuid.UUID
    unit_number: str
    order_index: int
    unit_type: str | None


def _roster(units: Sequence[StoryUnit]) -> list[_RosterUnit]:
    return [_RosterUnit(u.module_unit_id, u.unit_number, u.order_index, u.unit_type) for u in units]


def roster_digest(units: Sequence[StoryUnit]) -> str:
    """sha256 of the roster as canonical JSON (C-3): what a re-merge depends on.

    ``[[id, unit_number, order_index, role, title_en, title_fr], ...]`` in
    teaching order; a unit added, removed, moved, retyped or renamed changes it.
    """
    return content_digest(
        [
            [
                str(u.module_unit_id),
                u.unit_number,
                u.order_index,
                u.role,
                u.title["en"],
                u.title["fr"],
            ]
            for u in units
        ]
    )


async def load_story_units(session: AsyncSession, module_id: uuid.UUID) -> list[StoryUnit]:
    """The module's units in teaching order, each with its role — one query.

    Roles follow the completion API (``progress.complete_lesson``): a unit
    with no type or type ``"lesson"`` is a lesson; ``"case-study"`` and
    ``"scenario"`` are case checkpoints, and so is any other type whose unit
    holds cached case content (the #2163 safety net for syllabi that label a
    case study ``"quiz"``); everything else is a quiz checkpoint.
    """
    has_case = (
        exists()
        .where(
            GeneratedContent.module_unit_id == ModuleUnit.id,
            GeneratedContent.content_type == "case",
        )
        .label("has_case")
    )
    rows = (
        await session.execute(
            select(
                ModuleUnit.id,
                ModuleUnit.unit_number,
                ModuleUnit.order_index,
                ModuleUnit.unit_type,
                ModuleUnit.title_en,
                ModuleUnit.title_fr,
                has_case,
            ).where(ModuleUnit.module_id == module_id)
        )
    ).all()
    return [
        StoryUnit(
            module_unit_id=row.id,
            unit_number=str(row.unit_number),
            unit_type=row.unit_type,
            order_index=int(row.order_index or 0),
            role=unit_role(row.unit_type, has_case_content=bool(row.has_case)),
            title=_pair(row.title_en, row.title_fr),
        )
        for row in sorted(rows, key=_unit_order)
    ]


async def find_module_story(
    session: AsyncSession, module_id: uuid.UUID, language: str
) -> StoryCourseRecord | None:
    """The module story row of ``(module_id, language)``, if any."""
    return (
        await session.execute(
            select(StoryCourseRecord).where(
                StoryCourseRecord.module_id == module_id,
                StoryCourseRecord.language == language,
                StoryCourseRecord.module_unit_id.is_(None),
            )
        )
    ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Freshness
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _PlanState:
    """The stored plan as freshness reads it: its digests and each chapter's beat."""

    digest: str
    global_digest: str
    beats: dict[str, str]


@dataclass(frozen=True)
class _ChapterState:
    """A lesson unit's chapter row as freshness sees it (``content`` not loaded)."""

    story_id: uuid.UUID
    updated_at: datetime | None
    #: Told from the current bible, plan and sources.
    current: bool
    #: Published and valid: its chapter is in the story.
    ready: bool = True
    #: How many times it could not be made valid with these inputs.
    failures: int = 0

    @property
    def fresh(self) -> bool:
        """Nothing to tell again: current, and ready or failed too often."""
        return self.current and (self.ready or self.failures >= CHAPTER_FAILURE_CAP)


async def _plan_state(
    session: AsyncSession, module_id: uuid.UUID, language: str
) -> _PlanState | None:
    found = await find_plan_digests(session, module_id, language)
    if found is None:
        return None
    digest, global_digest, content = found
    beats = (content or {}).get("beats") if isinstance(content, dict) else None
    return _PlanState(digest, global_digest, dict(beats or {}))


def _expected(
    units: Sequence[StoryUnit], bible_digest: str | None, plan: _PlanState | None
) -> dict[uuid.UUID | None, dict[str, Any]] | None:
    if plan is None or bible_digest is None:
        return None
    return {
        u.module_unit_id: {
            "bible": bible_digest,
            "plan": plan.global_digest,
            "beat": plan.beats.get(str(u.module_unit_id)),
        }
        for u in units
        if u.role == "lesson"
    }


async def _chapter_states(
    session: AsyncSession,
    units: Sequence[StoryUnit],
    language: str,
    bible_digest: str | None,
    plan: _PlanState | None,
) -> dict[uuid.UUID, _ChapterState]:
    """Every lesson unit's chapter row and whether it is current — two queries.

    The chapter documents are not loaded: their generator version, their
    ``sira_chapter`` marker and their failure count are read in SQL, and
    every chapter's sources are checked in one query (:func:`chapters_are_fresh`).
    Without a stored plan no chapter is current.
    """
    lesson_ids = [u.module_unit_id for u in units if u.role == "lesson"]
    if not lesson_ids:
        return {}
    rows = (
        await session.execute(
            select(
                StoryCourseRecord,
                StoryCourseRecord.content["sira_builder"].label("builder"),
                StoryCourseRecord.content["sira_chapter"].label("marker"),
                StoryCourseRecord.source_rows["failures"].label("failures"),
            )
            .options(defer(StoryCourseRecord.content), defer(StoryCourseRecord.validation_report))
            .where(
                StoryCourseRecord.module_unit_id.in_(lesson_ids),
                StoryCourseRecord.language == language,
            )
        )
    ).all()
    if not rows:
        return {}
    records = [row[0] for row in rows]
    expected = _expected(units, bible_digest, plan)
    if expected is None:
        current = [False] * len(records)
    else:
        current = await chapters_are_fresh(
            session,
            records,
            builders=[row.builder for row in rows],
            markers=[row.marker for row in rows],
            covering=covering_quiz_units(_roster(units)),
            expected=expected,
        )
    return {
        record.module_unit_id: _ChapterState(
            record.id,
            record.updated_at,
            is_current,
            ready=record.status == "published" and bool(record.is_valid),
            failures=int(row.failures or 0) if isinstance(row.failures, int) else 0,
        )
        for row, record, is_current in zip(rows, records, current, strict=True)
        if record.module_unit_id is not None
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _is_module_row(record: StoryCourseRecord) -> bool:
    return record.module_id is not None and record.module_unit_id is None and bool(record.language)


def _module_story_matches(
    record: StoryCourseRecord,
    units: Sequence[StoryUnit],
    states: dict[uuid.UUID, _ChapterState],
    bible_digest: str | None,
    plan: _PlanState | None,
) -> bool:
    """Whether ``record`` was merged from exactly this roster, bible, plan and fresh chapters."""
    manifest = record.source_rows
    if not _is_module_row(record) or not isinstance(manifest, dict):
        return False
    if not _manifest_is_current(manifest, bible_digest, plan.digest if plan else None):
        return False
    if record.source_units_digest != roster_digest(units):
        return False
    entries = manifest.get("units")
    if not isinstance(entries, list) or [
        e.get("module_unit_id") if isinstance(e, dict) else None for e in entries
    ] != [str(u.module_unit_id) for u in units]:
        return False
    for unit, entry in zip(units, entries, strict=True):
        if unit.role != "lesson":
            continue
        state = states.get(unit.module_unit_id)
        if state is None or not state.fresh:
            return False
        if entry.get("chapter_story_id") != str(state.story_id):
            return False
        if entry.get("chapter_updated_at") != _iso(state.updated_at):
            return False
    return True


def _manifest_is_current(
    manifest: dict[str, Any], bible_digest: str | None, plan_digest: str | None = None
) -> bool:
    """The manifest's generator markers: assembler, chapter generator, bible and plan.

    A module story made by an older generator records another version, so it
    is stale and remade on next access. A draft the assembler itself failed to
    make valid is merged again on the next access (no model call: its
    chapters and rally are cached) — once: after
    :data:`ASSEMBLY_FAILURE_CAP` merges it counts as current, so the API
    answers 409 instead of starting a task on every poll.
    """
    failed = manifest.get("assembly_failed")
    failed = int(failed) if isinstance(failed, int | bool) else 0
    return (
        manifest.get("assembler") == MODULE_ASSEMBLER_VERSION
        and manifest.get("generator") == repair.CHAPTER_BUILDER_VERSION
        and bible_digest is not None
        and manifest.get("bible") == bible_digest
        and plan_digest is not None
        and manifest.get("plan") == plan_digest
        and (failed == 0 or failed >= ASSEMBLY_FAILURE_CAP)
    )


def _pinned_quiz_rows(manifest: Any) -> list[list[Any]]:
    """The quiz rows the rally was made from: ``[[id, revision, digest], ...]``."""
    rally = manifest.get("rally") if isinstance(manifest, dict) else None
    rows = rally.get("quiz_rows") if isinstance(rally, dict) else None
    return [row for row in rows or [] if isinstance(row, list) and len(row) == 3]


async def _rally_quizzes_unchanged(session: AsyncSession, manifest: Any) -> bool:
    """The exact quiz rows the rally used still hold the same revision and content.

    One query, and only for a module story with a rally. Which row would be
    chosen today (another level or country) is not asked: that would flap.
    """
    pinned = _pinned_quiz_rows(manifest)
    if not pinned:
        return True
    ids = []
    for row_id, _revision, _digest in pinned:
        try:
            ids.append(uuid.UUID(str(row_id)))
        except ValueError:
            return False
    rows = {
        row.id: row
        for row in (
            await session.execute(
                select(
                    GeneratedContent.id,
                    GeneratedContent.content_revision,
                    GeneratedContent.content,
                ).where(GeneratedContent.id.in_(ids))
            )
        ).all()
    }
    for row_id, revision, digest in pinned:
        row = rows.get(uuid.UUID(str(row_id)))
        if row is None or (row.content_revision or 1) != revision:
            return False
        if content_digest(row.content) != digest:
            return False
    return True


async def current_bible_digest(
    session: AsyncSession, course_id: uuid.UUID | None, *, is_kids: bool = False
) -> str | None:
    """The digest a module story of the course must have been told with.

    A course's stored bible (``None`` while it has none: nothing is fresh);
    for a module without a course, the audience's default bible.
    """
    if course_id is None:
        return default_bible(is_kids).digest
    return await find_bible_digest(session, course_id)


async def module_story_is_fresh(
    session: AsyncSession,
    record: StoryCourseRecord,
    *,
    units: Sequence[StoryUnit] | None = None,
) -> bool:
    """Whether a module story row can be served as it is — five queries, no model.

    Stale when it is not a module row, was built by another assembler or
    generator version, with another course bible or within another episode
    plan, the module's roster changed (:func:`roster_digest`), a lesson's
    chapter row is not the one (id and ``updated_at``) its manifest records,
    or any of those chapters is stale (:func:`chapters_are_fresh`, one batched
    query for all of them) — or, with a rally, when a quiz row the rally was
    made from was regenerated or edited (a sixth query).

    ``units`` is the module's current roster (:func:`load_story_units`) when
    the caller has just read it; it saves the first query.
    """
    if not _is_module_row(record) or not isinstance(record.source_rows, dict):
        return False
    module_id, language = record.module_id, record.language
    if module_id is None or language is None:
        return False
    if record.source_rows.get("assembler") != MODULE_ASSEMBLER_VERSION:
        return False
    if record.source_rows.get("generator") != repair.CHAPTER_BUILDER_VERSION:
        return False
    if units is None:
        units = await load_story_units(session, module_id)
    if record.source_units_digest != roster_digest(units):
        return False
    bible_digest = await current_bible_digest(session, record.course_id)
    if record.source_rows.get("bible") != bible_digest:
        return False
    plan = await _plan_state(session, module_id, language)
    if plan is None or record.source_rows.get("plan") != plan.digest:
        return False
    states = await _chapter_states(session, units, language, bible_digest, plan)
    if not _module_story_matches(record, units, states, bible_digest, plan):
        return False
    return await _rally_quizzes_unchanged(session, record.source_rows)


# --------------------------------------------------------------------------
# Figures that still exist (#2681: dead figures are never offered)
# --------------------------------------------------------------------------

#: The most figure binaries checked for one lesson, and the tries of each.
MAX_FIGURE_CHECKS, FIGURE_CHECK_TRIES = 5, 2


async def live_figures(
    session: AsyncSession, refs: Sequence[dict[str, Any]], storage: Any
) -> list[dict[str, Any]]:
    """The lesson's figure refs whose row and binary still exist, with their facts.

    One query of ``source_images`` for every ref (``image_hash``,
    ``figure_kind``, ``image_type``, size, storage keys), then a HEAD of each
    binary (at most :data:`MAX_FIGURE_CHECKS`, each tried
    :data:`FIGURE_CHECK_TRIES` times, a transport error also reading as
    missing). A ref whose row is gone or whose binary is missing is left out
    — a "show figure" step on it would be a dead card (#2598). The order of
    the rest is kept: FIGURE n is the n-th of them.
    """
    from app.domain.models.source_image import SourceImage

    ids: list[uuid.UUID] = []
    for ref in refs:
        try:
            ids.append(uuid.UUID(str(ref.get("id"))))
        except (TypeError, ValueError):
            continue
    if not ids:
        return []
    rows = {
        row.id: row
        for row in (
            await session.execute(
                select(
                    SourceImage.id,
                    SourceImage.image_hash,
                    SourceImage.figure_kind,
                    SourceImage.image_type,
                    SourceImage.width,
                    SourceImage.height,
                    SourceImage.storage_key,
                    SourceImage.storage_key_fr,
                    SourceImage.attribution,
                ).where(SourceImage.id.in_(ids))
            )
        ).all()
    }
    out: list[dict[str, Any]] = []
    checked = 0
    for ref in refs:
        try:
            row = rows.get(uuid.UUID(str(ref.get("id"))))
        except (TypeError, ValueError):
            row = None
        if row is None or not row.storage_key or checked >= MAX_FIGURE_CHECKS:
            continue
        checked += 1
        exists_ = False
        for _attempt in range(FIGURE_CHECK_TRIES):
            if await storage.object_exists(row.storage_key):
                exists_ = True
                break
        if not exists_:
            logger.warning("Story figure left out: binary missing", source_image_id=str(row.id))
            continue
        facts = dict(ref)
        facts.update(
            {
                "image_hash": row.image_hash,
                "figure_kind": row.figure_kind,
                "image_type": str(row.image_type) if row.image_type else None,
                "width": row.width,
                "height": row.height,
            }
        )
        if row.attribution and not facts.get("attribution"):
            facts["attribution"] = row.attribution
        out.append({k: v for k, v in facts.items() if v is not None})
    return out


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


@dataclass
class _Run:
    """One generation of a module story: its inputs and what the phases share."""

    module_id: uuid.UUID
    course_id: uuid.UUID | None
    language: str
    level: int
    country: str
    force: bool
    session_factory: Callable[[], Any]
    units: dict[uuid.UUID, StoryUnit]
    covering: dict[uuid.UUID, uuid.UUID | None]
    semaphore: asyncio.Semaphore
    deadline: float | None = None
    clock: Callable[[], float] = time.monotonic
    bible: StoryBible | None = None
    bible_error: BaseException | None = None
    quiz_locks: dict[uuid.UUID, asyncio.Lock] = field(default_factory=dict)
    quiz_ready: set[uuid.UUID] = field(default_factory=set)
    quiz_failed: dict[uuid.UUID, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    #: The rows the plan is made from, and the checked figures of each lesson.
    lesson_rows: dict[uuid.UUID, GeneratedContent] = field(default_factory=dict)
    quiz_rows: dict[uuid.UUID, GeneratedContent] = field(default_factory=dict)
    figures: dict[uuid.UUID, list[dict[str, Any]] | None] = field(default_factory=dict)
    request: PlanRequest | None = None
    plan: EpisodePlan | None = None
    told: list[str] = field(default_factory=list)
    #: Model calls of this run, by phase (for the cost report).
    calls: dict[str, int] = field(default_factory=dict)
    #: The packs kept with the plan (lesson unit id or "rally" → pack).
    packs_kept: dict[str, Any] = field(default_factory=dict)
    #: The packs whose model call has started (a stop lets them finish).
    packs_started: set[str] = field(default_factory=set)

    def time_left(self) -> float | None:
        return None if self.deadline is None else max(0.0, self.deadline - self.clock())

    def count(self, phase: str, calls: int) -> None:
        self.calls[phase] = self.calls.get(phase, 0) + calls

    def check_deadline(self) -> None:
        if self.deadline is not None and self.deadline - self.clock() < STORY_CALL_RESERVE_S:
            raise StoryDeadlineReached(list(self.told))


async def _has_content(
    session: AsyncSession, module_unit_id: uuid.UUID, content_type: str, language: str
) -> bool:
    found = (
        await session.execute(
            select(GeneratedContent.id)
            .where(
                GeneratedContent.module_unit_id == module_unit_id,
                GeneratedContent.content_type == content_type,
                GeneratedContent.language == language,
            )
            .limit(1)
        )
    ).first()
    return found is not None


def _dispatch_assessment(content_id: uuid.UUID) -> None:
    """Queue the quality assessment of a generated lesson, as the lesson task does."""
    try:
        from app.tasks.quality_assessment import assess_and_regenerate_unit_task

        assess_and_regenerate_unit_task.apply_async(
            kwargs={"content_id": str(content_id)}, priority=5
        )
    except Exception as exc:
        logger.warning(
            "Quality auto-assess dispatch failed (non-fatal)",
            content_id=str(content_id),
            error=str(exc)[:300],
        )


class ModuleStoryService:
    """Makes, caches and serves the story of a module (contract C-3, #2680)."""

    def __init__(
        self,
        claude_service: Any,
        lesson_service: Any,
        quiz_service: Any,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_repair_calls: int = MAX_REPAIR_CALLS,
        figure_storage: Any = None,
        stem_judge: Any = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.lesson_service = lesson_service
        self.quiz_service = quiz_service
        self.concurrency = concurrency
        # No lesson service of its own: every missing lesson is made in prep,
        # with its assessment dispatched.
        self.chapters = StoryFromLessonService(
            claude_service, lesson_service=None, max_repair_calls=max_repair_calls
        )
        self.bibles = StoryBibleService(claude_service)
        self.plans = StoryPlanService(claude_service)
        #: #2698: the cheaper configured model that judges each chapter's
        #: story-voiced quiz stems; ``None``: the quiz's own stems are kept.
        self.stem_judge = stem_judge
        #: ``object_exists(key)`` of the figure binaries; ``None``: not checked.
        self.figure_storage = figure_storage

    async def get_or_generate_module_story(
        self,
        module_id: uuid.UUID,
        language: str,
        session_factory: Callable[[], Any],
        *,
        level: int = 1,
        country: str = "CI",
        force_regenerate: bool = False,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> StoryCourseRecord:
        """Return the module story: planned, its stale chapters told in order, joined.

        ``session_factory()`` must give a new ``AsyncSession`` (an async
        context manager) per call. ``level`` and ``country`` only choose which
        missing lesson or quiz is generated and which cached row a module
        without a plan starts from (a plan pins its rows). ``force_regenerate``
        plans again and tells every chapter again (not the lessons, quizzes or
        the bible). ``deadline`` is a ``clock()`` time: no story call starts
        with less than :data:`STORY_CALL_RESERVE_S` left
        (:class:`StoryDeadlineReached`).

        Raises ``ValueError`` for an unknown module, :class:`NoStoryContent`
        when the module has no lesson unit, :class:`ChapterGenerationFailed`
        when a lesson, quiz, chapter or the rally could not be made (nothing
        is written for the module), :class:`StoryDeadlineReached`,
        :class:`story_bible.StoryBibleUnavailable` /
        :class:`story_bible.StoryProviderUnavailable` /
        :class:`story_plan.PlanCallImpossible` when the provider could not be
        used, and lets ``SoftTimeLimitExceeded`` through.
        """
        async with session_factory() as session:
            module = (
                await session.execute(
                    select(Module)
                    .options(selectinload(Module.course))
                    .where(Module.id == module_id)
                )
            ).scalar_one_or_none()
            if module is None:
                raise ValueError(f"Module {module_id} not found")
            units = await load_story_units(session, module_id)
            lessons = [u for u in units if u.role == "lesson"]
            if not lessons:
                raise NoStoryContent(f"Module {module_id} has no lesson unit")
            bible = await self._stored_bible(session, module)
            bible_digest = bible.digest if bible is not None else None
            plan_state = await _plan_state(session, module_id, language)
            states = await _chapter_states(session, units, language, bible_digest, plan_state)
            existing = await find_module_story(session, module_id, language)
            if (
                existing is not None
                and not force_regenerate
                and _module_story_matches(existing, units, states, bible_digest, plan_state)
                and await _rally_quizzes_unchanged(session, existing.source_rows)
            ):
                return existing
            previous_manifest = (
                existing.source_rows
                if existing is not None and isinstance(existing.source_rows, dict)
                else {}
            )
            stored_plan = await find_plan(session, module_id, language)
            pins = (
                (stored_plan.content or {}).get("pins") or {}
                if stored_plan is not None and isinstance(stored_plan.content, dict)
                else {}
            )
            course = module.course
            course_id = module.course_id
            module_number = module.module_number or 1
            module_title = _pair(module.title_en, module.title_fr)
            bible_modules = await _bible_modules(session, module) if bible is None else []
            previous_module = await _previous_module(session, module, language)

        run = _Run(
            module_id=module_id,
            course_id=course_id,
            language=language,
            level=level,
            country=country,
            force=force_regenerate,
            session_factory=session_factory,
            units={u.module_unit_id: u for u in units},
            covering=covering_quiz_units(_roster(units)),
            semaphore=asyncio.Semaphore(self.concurrency),
            deadline=deadline,
            clock=clock,
            bible=bible,
        )
        logger.info(
            "Module story: prep",
            module_id=str(module_id),
            language=language,
            lessons=len(lessons),
            force=force_regenerate,
        )
        await self._prep(run, course, bible_modules, lessons)
        bible = run.bible
        assert bible is not None  # _prep raised otherwise
        ctx = ModuleStoryContext(
            module_id=module_id,
            language=language,
            module_number=module_number,
            module_title=module_title,
            course_title=_pair(course.title_en, course.title_fr) if course else _pair("", ""),
            previous_module=(
                (previous_module["number"], previous_module["module_title"])
                if previous_module
                else None
            ),
            is_kids=_is_kids(course),
            bible=bible,
        )

        # -- 1. the episode plan ---------------------------------------------
        run.check_deadline()
        async with session_factory() as session:
            await self._read_sources(run, session, units, pins)
            run.request = self._plan_request(run, ctx, units, previous_module)
            plan_prompt = _system_prompt("plan", course, language, country, module_title)
            run.plan = await self.plans.get_or_create(
                session, run.request, system_prompt=plan_prompt, force=force_regenerate
            )
            run.count("plan", run.plan.calls)
            if not force_regenerate:
                run.packs_kept = await stored_packs(session, module_id, language)
            if self.figure_storage is not None:
                for unit in lessons:
                    row = run.lesson_rows[unit.module_unit_id]
                    refs = [
                        r
                        for r in (row.content or {}).get("source_image_refs") or []
                        if isinstance(r, dict) and r.get("id")
                    ]
                    run.figures[unit.module_unit_id] = await live_figures(
                        session, refs, self.figure_storage
                    )
        plan_digests = _PlanState(
            run.plan.digest,
            run.plan.global_digest,
            {
                **{
                    str(u.module_unit_id): run.plan.beat_digest(u.unit_number, run.request)
                    for u in lessons
                },
                **({"rally": run.plan.beat_digest(None, run.request)} if run.plan.rally else {}),
            },
        )

        # -- 2-4. packs, chapters in order, the rally ---------------------------
        async with session_factory() as session:
            states = await _chapter_states(session, units, language, bible.digest, plan_digests)
            rows = await _chapter_rows(session, language, units)
        stale = [
            u
            for u in lessons
            if force_regenerate
            or u.module_unit_id not in states
            or not states[u.module_unit_id].fresh
        ]
        logger.info(
            "Module story: telling chapters",
            module_id=str(module_id),
            language=language,
            chapters_to_tell=[u.unit_number for u in stale],
            plan_model=run.plan.model,
        )
        story_prompt = _system_prompt("screenplay", course, language, country, module_title)
        pack_prompt = _system_prompt("pack", course, language, country, module_title)
        rally_unit = next((u for u in reversed(units) if u.role == "quiz_checkpoint"), None)
        rally_previous = previous_manifest.get("rally")
        rally_pack_inputs = self._rally_pack_inputs(run) if run.plan.rally and rally_unit else None
        rally_pack_cached = (
            _fitting_pack(
                rally_previous.get("pack") if isinstance(rally_previous, dict) else None,
                run.packs_kept.get("rally"),
                inputs=rally_pack_inputs,
            )
            if rally_pack_inputs is not None and not force_regenerate
            else None
        )
        tasks: dict[str, asyncio.Task[Any]] = {}
        abort = True
        try:
            for unit in stale:
                tasks[unit.unit_number] = asyncio.create_task(
                    self._pack(run, ctx, unit, rows.get(unit.module_unit_id), pack_prompt),
                    name=f"story-pack-{unit.unit_number}",
                )
            if rally_unit is not None and run.plan.rally and rally_pack_cached is None:
                tasks["rally"] = asyncio.create_task(
                    self._rally_pack(run, ctx, rally_unit, pack_prompt), name="story-pack-rally"
                )
            docs = await self._tell(run, ctx, lessons, stale, states, rows, tasks, story_prompt)
            _raise_failures(run, lessons)
            rally = None
            if rally_unit is not None and run.plan.rally:
                rally_pack = (
                    rally_pack_cached if rally_pack_cached is not None else await tasks["rally"]
                )
                rally = await self._rally(
                    run,
                    ctx,
                    rally_unit,
                    lessons,
                    docs,
                    rows,
                    rally_pack,
                    previous=rally_previous,
                    system_prompt=story_prompt,
                )
            abort = False
        except (StoryDeadlineReached, ChapterGenerationFailed):
            abort = False  # a clean stop: the packs in flight are paid, keep them
            raise
        finally:
            await _settle_packs(run, tasks, abort=abort)
        record = await self._merge(
            session_factory, ctx, units, course_id, rally, run.plan, previous_manifest
        )
        logger.info(
            "Module story: model calls",
            module_id=str(module_id),
            language=language,
            calls=run.calls,
            total=sum(run.calls.values()),
        )
        return record

    # -- context ------------------------------------------------------------

    @staticmethod
    async def _stored_bible(session: AsyncSession, module: Module) -> StoryBible | None:
        """The course's stored bible; the default one for a module without a course."""
        from app.ai.prompts.audience import detect_audience

        if module.course_id is None or module.course is None:
            return default_bible(detect_audience(module.course).is_kids)
        row = await find_bible(session, module.course_id)
        if row is None or row.model == DEFAULTED:
            # None either way: a bible of defaults waits for its one retry.
            return None
        return StoryBible(content=row.content, digest=row.digest)

    # -- 0. prep --------------------------------------------------------------

    async def _prep(
        self,
        run: _Run,
        course: Any,
        bible_modules: list[BibleModule],
        lessons: Sequence[StoryUnit],
    ) -> None:
        """The bible, while every lesson and covering quiz is made if missing."""
        quiz_units = sorted(
            {q for u in lessons if (q := run.covering.get(u.module_unit_id)) is not None},
            key=lambda q: run.units[q].order_index,
        )
        try:
            async with asyncio.TaskGroup() as group:
                if run.bible is None:
                    group.create_task(self._ensure_bible(run, course, bible_modules))
                for unit in lessons:
                    group.create_task(self._prep_lesson(run, unit))
                for quiz_unit in quiz_units:
                    group.create_task(self._prep_quiz(run, run.units[quiz_unit]))
        except* SoftTimeLimitExceeded as limit:
            raise limit.exceptions[0] from None
        if run.bible_error is not None:
            raise run.bible_error
        if run.failures:
            _raise_failures(run, list(run.units.values()))

    async def _ensure_bible(self, run: _Run, course: Any, modules: list[BibleModule]) -> None:
        try:
            async with run.session_factory() as session:
                run.bible = await self.bibles.get_or_create(
                    session, course, modules, country=run.country
                )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.bible_error = exc

    async def _prep_lesson(self, run: _Run, unit: StoryUnit) -> None:
        try:
            async with run.semaphore, run.session_factory() as session:
                await self._ensure_lesson(run, session, unit)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.failures[unit.unit_number] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning(
                "Module story lesson failed",
                module_id=str(run.module_id),
                unit=unit.unit_number,
                error=str(exc)[:300],
            )

    async def _prep_quiz(self, run: _Run, quiz_unit: StoryUnit) -> None:
        try:
            async with run.semaphore, run.session_factory() as session:
                await self._ensure_quiz(run, session, quiz_unit)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            # Every lesson it covers fails: a chapter told without its quiz
            # would be paid for again once the quiz exists.
            for lesson, quiz in run.covering.items():
                if quiz == quiz_unit.module_unit_id and lesson in run.units:
                    run.failures[run.units[lesson].unit_number] = f"{type(exc).__name__}: {exc}"[
                        :300
                    ]

    async def _ensure_lesson(self, run: _Run, session: AsyncSession, unit: StoryUnit) -> None:
        """Generate the unit's lesson when none is cached in the language."""
        if await _has_content(session, unit.module_unit_id, "lesson", run.language):
            return
        if self.lesson_service is None:
            raise ValueError(f"No lesson is cached for unit {unit.unit_number} ({run.language})")
        with ai_usage_context(
            FEATURE_LESSON_GENERATION, module_id=run.module_id, course_id=run.course_id
        ):
            lesson = await self.lesson_service.get_or_generate_lesson(
                module_id=run.module_id,
                unit_id=unit.unit_number,
                language=run.language,
                country=run.country,
                level=run.level,
                session=session,
            )
        logger.info(
            "Lesson generated for a module story chapter",
            module_id=str(run.module_id),
            unit=unit.unit_number,
            language=run.language,
            content_id=str(lesson.id),
        )
        _dispatch_assessment(lesson.id)

    async def _ensure_quiz(self, run: _Run, session: AsyncSession, quiz_unit: StoryUnit) -> None:
        """Generate a covering quiz unit's quiz when it has none. A case study never gets one."""
        if self.quiz_service is None or quiz_unit.role != "quiz_checkpoint":
            return
        if await _has_content(session, quiz_unit.module_unit_id, "quiz", run.language):
            run.quiz_ready.add(quiz_unit.module_unit_id)
            return
        try:
            with ai_usage_context(
                FEATURE_QUIZ_GENERATION, module_id=run.module_id, course_id=run.course_id
            ):
                quiz = await self.quiz_service.get_or_generate_quiz(
                    module_id=run.module_id,
                    unit_id=quiz_unit.unit_number,
                    language=run.language,
                    country=run.country,
                    level=run.level,
                    session=session,
                )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.quiz_failed[quiz_unit.module_unit_id] = type(exc).__name__
            raise CoveringQuizUnavailable(
                f"The quiz of unit {quiz_unit.unit_number} could not be generated"
            ) from exc
        run.quiz_ready.add(quiz_unit.module_unit_id)
        logger.info(
            "Quiz generated for module story chapters",
            module_id=str(run.module_id),
            quiz_unit=quiz_unit.unit_number,
            language=run.language,
            content_id=str(getattr(quiz, "id", "")),
        )

    async def _read_sources(
        self,
        run: _Run,
        session: AsyncSession,
        units: Sequence[StoryUnit],
        pins: dict[str, Any],
    ) -> None:
        """Each lesson's and quiz unit's row: the plan's pinned one, else by level/country.

        Pinning keeps one story for every learner: a learner whose level or
        country picks another row never makes the plan (or the rally) stale.

        A covering unit's quiz row is read whatever its role, as freshness
        (:func:`chapters_are_fresh`) checks it: a unit typed "quiz" that holds
        a case study (a ``case_checkpoint``, #2163) and also has a quiz row
        would otherwise make the chapters it covers stale after every run.
        Only generating a quiz and telling the rally depend on the role.
        """
        pinned_lessons = pins.get("lessons") or {}
        pinned_quizzes = pins.get("quizzes") or {}
        covering = set(run.covering.values())
        for unit in units:
            if unit.role == "lesson":
                row = await _pick_row(session, run, unit.module_unit_id, "lesson", pinned_lessons)
                if row is None:
                    raise ChapterGenerationFailed(
                        [unit.unit_number], {unit.unit_number: "no lesson row"}
                    )
                run.lesson_rows[unit.module_unit_id] = row
            elif unit.role == "quiz_checkpoint" or unit.module_unit_id in covering:
                row = await _pick_row(session, run, unit.module_unit_id, "quiz", pinned_quizzes)
                if row is not None:
                    run.quiz_rows[unit.module_unit_id] = row

    def _plan_request(
        self,
        run: _Run,
        ctx: ModuleStoryContext,
        units: Sequence[StoryUnit],
        previous_module: dict[str, Any] | None,
    ) -> PlanRequest:
        """The plan's inputs: fact sheets, blocklist, the course questions as candidates."""
        from app.ai.prompts.story_from_lesson import build_fact_sheet, build_name_blocklist

        bible = ctx.story_bible
        lessons = [u for u in units if u.role == "lesson"]
        covered: dict[uuid.UUID, list[str]] = {}
        for lesson in lessons:
            quiz = run.covering.get(lesson.module_unit_id)
            if quiz is not None:
                covered.setdefault(quiz, []).append(lesson.unit_number)
        candidates: list[PlanCandidate] = []
        quiz_rows: list[list[Any]] = []
        stems: list[str] = []
        for unit in units:
            row = run.quiz_rows.get(unit.module_unit_id)
            if row is None:
                continue
            mcqs, _dropped = repair.parse_quiz_mcqs((row.content or {}).get("questions"))
            quiz_rows.append(
                [
                    str(unit.module_unit_id),
                    str(row.id),
                    row.content_revision or 1,
                    sha([mcq_key(m) for m in mcqs]),
                ]
            )
            for mcq in mcqs:
                mcq.ref = f"q{len(candidates) + 1}"
                mcq.quiz_unit = unit.unit_number
                stems.append(mcq.stem)
                candidates.append(
                    PlanCandidate(
                        ref=mcq.ref,
                        mcq=mcq,
                        quiz_unit=unit.unit_number,
                        covers=tuple(covered.get(unit.module_unit_id, [])),
                    )
                )
        plan_lessons = [
            PlanLesson(
                unit_id=u.module_unit_id,
                unit_number=u.unit_number,
                title=dict(u.title),
                sheet=build_fact_sheet(run.lesson_rows[u.module_unit_id].content),
                lesson_row_id=run.lesson_rows[u.module_unit_id].id,
            )
            for u in lessons
        ]
        blocklist = build_name_blocklist(
            [run.lesson_rows[u.module_unit_id].content or {} for u in lessons],
            stems,
            bible.content,
            country=run.country,
        )
        return PlanRequest(
            module_id=run.module_id,
            language=run.language,
            is_kids=ctx.is_kids,
            module_number=ctx.module_number,
            module_title=dict(ctx.module_title),
            course_title=dict(ctx.course_title),
            bible=bible,
            lessons=plan_lessons,
            candidates=candidates,
            quiz_rows=quiz_rows,
            roster_digest=roster_digest(units),
            has_rally=any(u.role == "quiz_checkpoint" for u in units),
            blocklist=blocklist,
            mission=mission_for(bible.content, ctx.module_id, ctx.module_number, ctx.module_title),
            previous=(
                {
                    "number": previous_module["number"],
                    "title": previous_module.get("episode_title")
                    or previous_module["module_title"][run.language],
                    "logline": previous_module.get("logline", ""),
                }
                if previous_module and previous_module.get("logline")
                else None
            ),
            pins={
                "lessons": {str(k): str(v.id) for k, v in run.lesson_rows.items()},
                "quizzes": {str(k): str(v.id) for k, v in run.quiz_rows.items()},
            },
        )

    # -- the context of a chapter -------------------------------------------------

    def _chapter_ctx(
        self, run: _Run, ctx: ModuleStoryContext, unit: StoryUnit
    ) -> repair.LessonStoryContext:
        """A lesson chapter's context from the plan (no neighbours yet)."""
        from app.ai.prompts.story_from_lesson import fact_sheet_digest

        assert run.plan is not None and run.request is not None
        plan = run.plan
        entry = plan.chapter(unit.unit_number) or {}
        lessons = [u for u in run.units.values() if u.role == "lesson"]
        lessons.sort(key=lambda u: u.order_index)
        index = next(i for i, u in enumerate(lessons) if u.module_unit_id == unit.module_unit_id)
        refs = entry_refs(entry)
        mcqs = self._mcqs(run, refs)
        quiz_unit = run.covering.get(unit.module_unit_id)
        row = run.lesson_rows[unit.module_unit_id]
        return repair.LessonStoryContext(
            module_unit_id=unit.module_unit_id,
            language=run.language,
            unit_number=unit.unit_number,
            unit_title=dict(unit.title),
            module_title=dict(ctx.module_title),
            course_title=dict(ctx.course_title),
            module_number=ctx.module_number,
            lesson=dict(row.content or {}),
            mcqs=mcqs,
            has_quiz=bool(mcqs),
            is_kids=ctx.is_kids,
            quiz_scope="assigned",
            quiz_unit_number=run.units[quiz_unit].unit_number if quiz_unit else None,
            bible=ctx.story_bible.content,
            country=row.country_context or run.country,
            plan=plan.plan,
            plan_entry=entry,
            plan_defaulted=plan.made_in_code(unit.unit_number),
            chapter_index=index + 1,
            chapter_count=len(lessons),
            assigned_refs=[m.ref for m in mcqs],
            has_game=bool(entry.get("game")),
            catchphrases=list(plan.plan.get("catchphrases") or []),
            blocklist=list(run.request.blocklist),
            fact_sheet_digest=fact_sheet_digest(row.content),
            plan_global_digest=plan.global_digest,
            beat_digest=plan.beat_digest(unit.unit_number, run.request),
            figures=run.figures.get(unit.module_unit_id),
            # The plan's props; the chapters told before add theirs (_neighbours).
            known_props=plan_props(plan.plan),
        )

    def _mcqs(self, run: _Run, refs: list[str]) -> list[repair.QuizMcq]:
        assert run.request is not None
        out = []
        for ref in refs:
            candidate = run.request.candidate(ref)
            if candidate is not None:
                mcq = copy.deepcopy(candidate.mcq)
                mcq.ref = ref
                out.append(mcq)
        return out

    def _pack_inputs(self, run: _Run, ctx: repair.LessonStoryContext) -> str:
        return sha(
            [
                repair.PACK_VERSION,
                ctx.beat_digest,
                ctx.fact_sheet_digest,
                [_mcq_content(m) for m in ctx.mcqs],
            ]
        )

    def _rally_pack_inputs(self, run: _Run) -> str:
        assert run.plan is not None and run.request is not None
        refs = entry_refs(run.plan.rally, rally=True)
        return sha(
            [
                repair.PACK_VERSION,
                run.plan.beat_digest(None, run.request),
                run.plan.global_digest,
                [_mcq_content(m) for m in self._mcqs(run, refs)],
            ]
        )

    # -- 2. packs -----------------------------------------------------------------

    async def _pack(
        self,
        run: _Run,
        ctx: ModuleStoryContext,
        unit: StoryUnit,
        row: StoryCourseRecord | None,
        system_prompt: str,
    ) -> dict[str, Any] | None:
        """A chapter's practice pack: kept (chapter row or plan) when its inputs match, else made."""
        chapter = self._chapter_ctx(run, ctx, unit)
        inputs = self._pack_inputs(run, chapter)
        key = str(unit.module_unit_id)
        if not run.force:
            kept = _fitting_pack(
                (row.source_rows or {}).get("pack") if row is not None else None,
                run.packs_kept.get(key),
                inputs=inputs,
            )
            if kept is not None:
                return kept
        try:
            async with run.semaphore:
                run.packs_started.add(unit.unit_number)
                with ai_usage_context(
                    FEATURE_STORY_GENERATION, module_id=run.module_id, course_id=run.course_id
                ):
                    result = await self.chapters.generate_pack(chapter, system_prompt=system_prompt)
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.failures[unit.unit_number] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("Module story pack failed", unit=unit.unit_number, error=str(exc)[:300])
            return None
        run.count("packs", result.model_calls)
        made = {"inputs": inputs, "spine": result.pack}
        await _keep_pack(run, key, made)
        return made

    async def _rally_pack(
        self, run: _Run, ctx: ModuleStoryContext, rally_unit: StoryUnit, system_prompt: str
    ) -> dict[str, Any] | None:
        rally_ctx = self._rally_ctx(run, ctx, rally_unit, from_plan=True)
        try:
            async with run.semaphore:
                run.packs_started.add("rally")
                with ai_usage_context(
                    FEATURE_STORY_GENERATION, module_id=run.module_id, course_id=run.course_id
                ):
                    result = await self.chapters.generate_pack(
                        rally_ctx, system_prompt=system_prompt
                    )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.failures[rally_unit.unit_number] = f"{type(exc).__name__}: {exc}"[:300]
            return None
        run.count("packs", result.model_calls)
        made = {"inputs": self._rally_pack_inputs(run), "spine": result.pack}
        await _keep_pack(run, "rally", made)
        return made

    async def _story_stems(
        self, run: _Run, chapter: repair.LessonStoryContext, pack: dict[str, Any], key: str
    ) -> dict[str, dict[str, str]]:
        """The approved story stems of a chapter's course questions (#2698).

        Judged once per pack: the verdict is kept with the pack (``stems``)
        and with the plan, so telling the chapter again, or after a stop,
        never asks the judge again. A verdict that could not be reached (no
        judge, a provider error) is not kept: the original stems are used and
        the next telling asks once more.
        """
        kept = pack.get("stems")
        if isinstance(kept, dict) and kept.get("version") == STEM_JUDGE_VERSION:
            return approved_stems(kept)
        with ai_usage_context(
            FEATURE_STORY_GENERATION, module_id=run.module_id, course_id=run.course_id
        ):
            verdict = await approve_stems(chapter, pack["spine"], self.stem_judge)
        if verdict is None:
            return {}
        run.count("stems", int(verdict.pop("calls", 0)))
        pack["stems"] = verdict
        await _keep_pack(run, key, pack)
        return approved_stems(verdict)

    # -- 3. the chapters, in order ---------------------------------------------------

    async def _tell(
        self,
        run: _Run,
        ctx: ModuleStoryContext,
        lessons: Sequence[StoryUnit],
        stale: Sequence[StoryUnit],
        states: dict[uuid.UUID, _ChapterState],
        rows: dict[uuid.UUID | None, StoryCourseRecord],
        packs: dict[str, asyncio.Task[Any]],
        system_prompt: str,
    ) -> dict[str, dict[str, Any] | None]:
        """Tell the stale chapters in teaching order; return every chapter's usable doc.

        A chapter is told after the one before it: from that chapter's real
        last scene (built in this run, or stored), the recaps of every chapter
        before it and the props as they stand. A chapter that fails is
        recorded and the next one opens on the plan's OPENS ON.
        """
        stale_ids = {u.module_unit_id for u in stale}
        docs: dict[str, dict[str, Any] | None] = {}
        extras: dict[str, dict[str, Any]] = {}
        for unit in lessons:
            row = rows.get(unit.module_unit_id)
            if unit.module_unit_id not in stale_ids:
                docs[unit.unit_number] = _usable_doc(row)
                extras[unit.unit_number] = dict((row.source_rows or {}) if row else {})
        for position, unit in enumerate(lessons):
            if unit.module_unit_id not in stale_ids:
                continue
            pack = await packs[unit.unit_number]
            if pack is None:
                docs[unit.unit_number] = None
                continue
            run.check_deadline()
            chapter = self._chapter_ctx(run, ctx, unit)
            self._neighbours(chapter, run, lessons, position, docs, extras, rows, states)
            chapter.pack_digest = pack["inputs"]
            chapter.story_stems = await self._story_stems(
                run, chapter, pack, str(unit.module_unit_id)
            )
            try:
                with ai_usage_context(
                    FEATURE_STORY_GENERATION, module_id=run.module_id, course_id=run.course_id
                ):
                    generation = await self.chapters.generate_story(
                        chapter, pack["spine"], system_prompt=system_prompt
                    )
            except SoftTimeLimitExceeded:
                raise
            except Exception as exc:
                run.failures[unit.unit_number] = f"{type(exc).__name__}: {exc}"[:300]
                logger.warning(
                    "Module story chapter failed",
                    module_id=str(run.module_id),
                    unit=unit.unit_number,
                    error_type=type(exc).__name__,
                    error=str(exc)[:300],
                )
                docs[unit.unit_number] = None
                continue
            run.count("stories", generation.model_calls)
            record = await self._persist_chapter(
                run, unit, chapter, generation, pack, rows.get(unit.module_unit_id)
            )
            rows[unit.module_unit_id] = record
            extras[unit.unit_number] = dict(record.source_rows or {})
            if generation.report.ok:
                docs[unit.unit_number] = generation.doc
                run.told.append(unit.unit_number)
            else:
                docs[unit.unit_number] = None
                failures = int((record.source_rows or {}).get("failures") or 0)
                if failures < CHAPTER_FAILURE_CAP:
                    run.failures[unit.unit_number] = (
                        "chapter could not be made valid: "
                        + (", ".join(sorted({e.code for e in generation.report.errors}))[:200])
                    )
        return docs

    def _neighbours(
        self,
        chapter: repair.LessonStoryContext,
        run: _Run,
        lessons: Sequence[StoryUnit],
        position: int,
        docs: dict[str, dict[str, Any] | None],
        extras: dict[str, dict[str, Any]],
        rows: dict[uuid.UUID | None, StoryCourseRecord],
        states: dict[uuid.UUID, _ChapterState],
    ) -> None:
        """What a chapter knows of the others: the story so far, its last scene, the next."""
        assert run.plan is not None
        lang = run.language
        earlier = lessons[:position]
        chapter.story_so_far = [
            {
                "unit": u.unit_number,
                "title": (run.plan.chapter(u.unit_number) or {}).get("title") or u.title,
                "recap": (extras.get(u.unit_number) or {}).get("recap", ""),
            }
            for u in earlier
        ]
        for u in reversed(earlier):
            props_now = (extras.get(u.unit_number) or {}).get("props_now")
            if isinstance(props_now, list) and props_now:
                chapter.props_now = props_now
                break
        if earlier:
            before = docs.get(earlier[-1].unit_number)
            if before is None:
                chapter.previous_missing = True
            else:
                chapter.previous_scene = scene_summary(before, lang, last=True)
                chapter.prev_digest = sha(
                    [chapter.previous_scene, chapter.story_so_far[-1]["recap"]]
                )
        if position + 1 < len(lessons):
            after = lessons[position + 1]
            state = states.get(after.module_unit_id)
            if state is not None and state.fresh and state.ready:
                next_doc = _usable_doc(rows.get(after.module_unit_id))
                if next_doc is not None:
                    chapter.next_scene = scene_summary(next_doc, lang, last=False)
        known = plan_props(run.plan.plan)
        seen = {p["id"] for p in known}
        for u in earlier:
            doc = docs.get(u.unit_number)
            for prop in (doc or {}).get("props") or []:
                if prop.get("id") not in seen:
                    seen.add(prop["id"])
                    known.append({**prop, "origin": u.unit_number})
        chapter.known_props = known
        lines: dict[tuple[str, str], str] = {}
        refrains = 0
        for u in earlier:
            for step in _steps(docs.get(u.unit_number)):
                if step.get("refrain"):
                    refrains += 1
                    continue
                for key in repair.repeat_keys(step):
                    lines.setdefault(key, u.unit_number)
        chapter.earlier_line_keys = lines
        chapter.refrains_before = refrains

    async def _persist_chapter(
        self,
        run: _Run,
        unit: StoryUnit,
        chapter: repair.LessonStoryContext,
        generation: Any,
        pack: dict[str, Any],
        previous: StoryCourseRecord | None,
    ) -> StoryCourseRecord:
        lesson_row = run.lesson_rows[unit.module_unit_id]
        quiz_unit = run.covering.get(unit.module_unit_id)
        quiz_row = run.quiz_rows.get(quiz_unit) if quiz_unit is not None else None
        digests = {
            "plan": chapter.plan_global_digest,
            "beat": chapter.beat_digest,
            "fact_sheet": chapter.fact_sheet_digest,
        }
        failures = 0
        if not generation.report.ok:
            before = (previous.source_rows or {}) if previous is not None else {}
            same = before.get("digests") == digests
            failures = (int(before.get("failures") or 0) if same else 0) + 1
        spine = generation.spine or {}
        source_rows = {
            "pack": pack,
            "recap": _plain(spine.get("recap"), 600),
            "props_now": [
                {"id": str(p.get("id")), "state": _plain(p.get("state"), 200)}
                for p in spine.get("props_now") or []
                if isinstance(p, dict) and p.get("id")
            ][:8],
            "digests": digests,
            "handoff": chapter.prev_digest,
            "failures": failures,
        }
        binding = StoryBinding(
            module_id=run.module_id,
            module_unit_id=unit.module_unit_id,
            language=run.language,
            lesson_content_id=lesson_row.id,
            lesson_revision=lesson_row.content_revision or 1,
            quiz_content_id=quiz_row.id if quiz_row is not None else None,
            quiz_revision=(quiz_row.content_revision or 1) if quiz_row is not None else None,
            lesson_digest=content_digest(lesson_row.content),
            quiz_digest=content_digest(quiz_row.content) if quiz_row is not None else None,
            source_rows=source_rows,
        )
        async with run.session_factory() as session:
            module = await session.get(Module, run.module_id)
            return await self.chapters._persist(
                session, generation, binding, module.course_id if module else run.course_id
            )

    # -- 4. the rally ----------------------------------------------------------------

    def _rally_ctx(
        self,
        run: _Run,
        ctx: ModuleStoryContext,
        rally_unit: StoryUnit,
        *,
        from_plan: bool,
        docs: dict[str, dict[str, Any] | None] | None = None,
    ) -> repair.LessonStoryContext:
        """The rally's context: from the plan (its pack), or from the told chapters."""
        assert run.plan is not None and run.request is not None
        plan = run.plan
        entry = plan.rally or {}
        refs = entry_refs(entry, rally=True)
        mcqs = self._mcqs(run, refs)
        lang = run.language
        ideas: list[dict[str, Any]] = []
        for lesson in run.request.lessons:
            chapter = plan.chapter(lesson.unit_number) or {}
            doc = (docs or {}).get(lesson.unit_number)
            if from_plan or doc is None:
                cards = [
                    {
                        "title": (b.get("card_title") or {}).get(lang, ""),
                        "rows": [(b.get("discovery") or {}).get(lang, "")],
                    }
                    for b in chapter.get("beats") or []
                ]
            else:
                cards = [
                    {"title": (s.get("title") or {}).get(lang, ""), "rows": list(s.get(lang) or [])}
                    for s in _steps(doc)
                    if s.get("type") == "concept"
                    and not str(s.get("id", "")).startswith("situation-")
                ]
            ideas.append(
                {"unit": lesson.unit_number, "title": chapter.get("title"), "cards": cards}
            )
        return repair.LessonStoryContext(
            module_unit_id=rally_unit.module_unit_id,
            language=lang,
            unit_number=rally_unit.unit_number,
            unit_title=dict(rally_unit.title),
            module_title=dict(ctx.module_title),
            course_title=dict(ctx.course_title),
            module_number=ctx.module_number,
            lesson={},
            mcqs=mcqs,
            has_quiz=bool(mcqs),
            is_kids=ctx.is_kids,
            quiz_scope="assigned",
            quiz_unit_number=rally_unit.unit_number,
            kind="rally",
            bible=ctx.story_bible.content,
            country=run.country,
            plan=plan.plan,
            plan_entry=entry,
            plan_defaulted=plan.made_in_code(None),
            chapter_index=len(run.request.lessons) + 1,
            chapter_count=len(run.request.lessons),
            assigned_refs=[m.ref for m in mcqs],
            has_game=bool(entry.get("game")),
            catchphrases=list(plan.plan.get("catchphrases") or []),
            blocklist=list(run.request.blocklist),
            plan_global_digest=plan.global_digest,
            beat_digest=plan.beat_digest(None, run.request),
            episode_ideas=ideas,
            max_picks=repair.MAX_RALLY_PICKS,
        )

    async def _rally(
        self,
        run: _Run,
        ctx: ModuleStoryContext,
        rally_unit: StoryUnit,
        lessons: Sequence[StoryUnit],
        docs: dict[str, dict[str, Any] | None],
        rows: dict[uuid.UUID | None, StoryCourseRecord],
        pack: dict[str, Any] | None,
        *,
        previous: Any,
        system_prompt: str,
    ) -> dict[str, Any] | None:
        """The rally's manifest entry: told now, or the previous one when its inputs match.

        Its inputs are the builder, the bible, the plan, its entry, the
        chapters' recaps and the exact quiz rows it uses (pinned by the plan,
        so a learner of another level or country never pays for a new rally).
        """
        assert run.plan is not None and run.request is not None
        recaps = [
            (rows.get(u.module_unit_id).source_rows or {}).get("recap", "")
            if rows.get(u.module_unit_id) is not None
            else ""
            for u in lessons
        ]
        refs = entry_refs(run.plan.rally, rally=True)
        quiz_units = sorted(
            {c.quiz_unit for ref in refs if (c := run.request.candidate(ref)) is not None}
        )
        pinned = [
            [str(row.id), row.content_revision or 1, content_digest(row.content)]
            for unit_id, row in run.quiz_rows.items()
            if run.units[unit_id].unit_number in quiz_units
        ]
        inputs = sha(
            [
                repair.CHAPTER_BUILDER_VERSION,
                ctx.story_bible.digest,
                run.plan.global_digest,
                run.plan.rally,
                sha(recaps),
                pinned,
            ]
        )
        if (
            not run.force
            and isinstance(previous, dict)
            and previous.get("inputs") == inputs
            and previous.get("status") in ("ready", "draft", "none")
        ):
            return {**previous, "quiz_rows": pinned}
        if pack is None:
            raise ChapterGenerationFailed(
                [rally_unit.unit_number], {rally_unit.unit_number: "no practice pack"}
            )
        rally_ctx = self._rally_ctx(run, ctx, rally_unit, from_plan=False, docs=docs)
        self._neighbours(
            rally_ctx, run, lessons, len(lessons), docs, _extras(rows, lessons), rows, {}
        )
        rally_ctx.props_seen = _props_seen(docs)
        rally_ctx.pack_digest = pack["inputs"]
        run.check_deadline()
        rally_ctx.story_stems = await self._story_stems(run, rally_ctx, pack, "rally")
        try:
            with ai_usage_context(
                FEATURE_STORY_GENERATION, module_id=ctx.module_id, course_id=run.course_id
            ):
                generation = await self.chapters.generate_story(
                    rally_ctx,
                    pack["spine"],
                    system_prompt=system_prompt,
                    max_repair_calls=RALLY_REPAIR_CALLS,
                )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            number = rally_unit.unit_number
            logger.warning(
                "Module story rally failed",
                module_id=str(ctx.module_id),
                language=ctx.language,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            raise ChapterGenerationFailed(
                [number], {number: f"{type(exc).__name__}: {exc}"[:300]}
            ) from exc
        run.count("stories", generation.model_calls)
        ok = generation.report.ok
        logger.info(
            "Module story rally made",
            module_id=str(ctx.module_id),
            language=ctx.language,
            ok=ok,
            questions=len(generation.doc.get("questions") or []),
            model_calls=generation.model_calls,
        )
        return {
            "inputs": inputs,
            # The exact quiz rows it was made from: an edit of one makes the
            # module story stale (module_story_is_fresh).
            "quiz_rows": pinned,
            "pack": pack,
            "status": "ready" if ok else "draft",
            "doc": generation.doc if ok else None,
            "errors": sorted({issue.code for issue in generation.report.errors})[:10],
        }

    # -- 5. the module row ------------------------------------------------------------

    async def _merge(
        self,
        session_factory: Callable[[], Any],
        ctx: ModuleStoryContext,
        units: Sequence[StoryUnit],
        course_id: uuid.UUID | None,
        rally: dict[str, Any] | None,
        plan: EpisodePlan,
        previous_manifest: dict[str, Any],
    ) -> StoryCourseRecord:
        """Assemble the cached chapters and the rally, validate, and store the module row."""
        async with session_factory() as session:
            rows = await _chapter_rows(session, ctx.language, units)
            sources: list[ChapterSource] = []
            chapter_rows: list[StoryCourseRecord | None] = []
            for unit in units:
                row = rows.get(unit.module_unit_id) if unit.role == "lesson" else None
                sources.append(ChapterSource(unit=unit, doc=_usable_doc(row)))
                chapter_rows.append(row)

            rally_doc = rally.get("doc") if isinstance(rally, dict) else None
            ctx = ModuleStoryContext(
                **{**ctx.__dict__, "episode_title": plan.plan.get("episode_title")}
            )
            doc = assemble_module_story(ctx, sources, rally_doc)
            report = validate_module_story(doc)
            doc["checks"] = report.checks.model_dump(mode="json")
            entries: list[dict[str, Any]] = [
                {
                    "module_unit_id": str(unit.module_unit_id),
                    "unit_number": unit.unit_number,
                    "role": unit.role,
                    "status": _chapter_status(doc, index, source),
                    "chapter_story_id": str(row.id) if row is not None else None,
                    "chapter_updated_at": _iso(row.updated_at) if row is not None else None,
                }
                for index, (unit, source, row) in enumerate(
                    zip(units, sources, chapter_rows, strict=True)
                )
            ]
            manifest: dict[str, Any] = {
                "assembler": MODULE_ASSEMBLER_VERSION,
                "generator": repair.CHAPTER_BUILDER_VERSION,
                "bible": ctx.story_bible.digest,
                "plan": plan.digest,
                "units": entries,
            }
            if rally is not None:
                manifest["rally"] = rally
            statuses = [entry["status"] for entry in entries]
            if not report.ok and "ready" in statuses:
                # Merged again once at no model cost (its chapters and rally
                # are cached); a second failure with the same chapters is
                # final until something changes, and the API answers 409.
                same = (
                    previous_manifest.get("units") == entries
                    and previous_manifest.get("plan") == plan.digest
                )
                before = previous_manifest.get("assembly_failed") if same else 0
                manifest["assembly_failed"] = (int(before) if isinstance(before, int) else 0) + 1
            if not report.ok:
                log = logger.error if "ready" in statuses else logger.warning
                log(
                    "Module story is not publishable; stored as a draft",
                    module_id=str(ctx.module_id),
                    language=ctx.language,
                    codes=sorted({issue.code for issue in report.errors}),
                    statuses=statuses,
                    merges=manifest.get("assembly_failed"),
                )
            try:
                course = StoryCourse.model_validate(doc)
            except Exception as exc:
                logger.error(
                    "Module story does not parse (assembler bug); nothing stored",
                    module_id=str(ctx.module_id),
                    language=ctx.language,
                    error=str(exc)[:500],
                )
                raise ModuleStoryAssemblyFailed(str(exc)[:500]) from exc

            binding = ModuleStoryBinding(
                module_id=ctx.module_id,
                language=ctx.language,
                source_rows=manifest,
                units_digest=roster_digest(units),
            )
            for attempt in range(2):
                try:
                    record = await upsert_story_course(
                        session,
                        course=course,
                        content=doc,
                        report=report,
                        course_id=course_id,
                        publish=report.ok,
                        binding=binding,
                    )
                    await session.commit()
                    await session.refresh(record)
                    break
                except IntegrityError:
                    # Another worker stored this module story first; update it.
                    await session.rollback()
                    if attempt:
                        raise
        logger.info(
            "Module story stored",
            slug=module_story_slug(ctx.module_id, ctx.language),
            status=record.status,
            is_valid=record.is_valid,
            max_points=record.max_points,
            statuses=statuses,
        )
        return record


def _raise_failures(run: _Run, units: Sequence[StoryUnit]) -> None:
    """Raise :class:`ChapterGenerationFailed` when any of ``units``' chapters failed."""
    if not run.failures:
        return
    numbers = [u.unit_number for u in sorted(units, key=lambda u: u.order_index)]
    failed = [n for n in numbers if n in run.failures] + [
        n for n in run.failures if n not in numbers
    ]
    logger.warning(
        "Module story not written: chapters failed",
        module_id=str(run.module_id),
        language=run.language,
        failed_units=failed,
    )
    raise ChapterGenerationFailed(failed, run.failures)


def _chapter_status(doc: dict[str, Any], index: int, source: ChapterSource) -> str:
    """The status the assembler gave the unit's chapter (its ``covers``).

    Quiz, case-study and scenario units have no chapter of their own (the
    rally covers the last quiz unit): ``"checkpoint"``.
    """
    if source.unit.role != "lesson":
        return "checkpoint"
    for chapter in doc.get("chapters") or []:
        covers = chapter.get("covers") if isinstance(chapter, dict) else None
        if (
            isinstance(covers, dict)
            and covers.get("module_unit_id") == str(source.unit.module_unit_id)
            and covers.get("status") in ("ready", "unavailable")
        ):
            return str(covers["status"])
    return "ready" if source.doc is not None else "unavailable"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _is_kids(course: Any) -> bool:
    from app.ai.prompts.audience import detect_audience

    return detect_audience(course).is_kids


def _system_prompt(
    kind: str, course: Any, language: str, country: str, module_title: dict[str, str]
) -> str:
    from app.ai.prompts.story_from_lesson import get_story_v4_system_prompt

    def in_target(en: str | None, fr: str | None) -> str | None:
        return fr if language == "fr" else en

    return get_story_v4_system_prompt(
        kind,
        language=language,
        country=country,
        course=course,
        course_title=in_target(course.title_en, course.title_fr) if course else None,
        module_title=module_title[language],
    )


def _fitting_pack(*kept: Any, inputs: str | None) -> dict[str, Any] | None:
    """The first kept pack made from exactly ``inputs``: ``{"inputs", "spine"}``,
    with its story stems' verdict (``stems``, #2698) when it has one."""
    for pack in kept:
        if (
            inputs is not None
            and isinstance(pack, dict)
            and pack.get("inputs") == inputs
            and isinstance(pack.get("spine"), dict)
        ):
            fitting = {"inputs": inputs, "spine": pack["spine"]}
            if isinstance(pack.get("stems"), dict):
                fitting["stems"] = pack["stems"]
            return fitting
    return None


async def _keep_pack(run: _Run, key: str, pack: dict[str, Any]) -> None:
    """Keep a pack with the plan as soon as it is made; a failure to keep it is logged."""
    try:
        async with run.session_factory() as session:
            await save_pack(session, run.module_id, run.language, key, pack)
    except SoftTimeLimitExceeded:
        raise
    except Exception as exc:
        logger.warning("Module story pack not kept", key=key, error=str(exc)[:300])


async def _settle_packs(run: _Run, tasks: dict[str, asyncio.Task[Any]], *, abort: bool) -> None:
    """End the pack tasks when the chapters are done or the run stops.

    A pack still waiting for its turn is cancelled: nothing was paid. On a
    clean stop (a deadline, a failed chapter) a pack whose call has started is
    paid for: it is let finish, within the time left, and kept
    (:func:`_keep_pack`), so the next run never pays for it again. ``abort``
    (a time limit, a cancellation, a bug) cancels everything.
    """
    waiting: list[asyncio.Task[Any]] = []
    for key, task in tasks.items():
        if task.done():
            continue
        if abort or key not in run.packs_started:
            task.cancel()
        else:
            waiting.append(task)
    if waiting:
        _done, pending = await asyncio.wait(waiting, timeout=run.time_left())
        for task in pending:
            task.cancel()
    await asyncio.gather(*tasks.values(), return_exceptions=True)


async def _pick_row(
    session: AsyncSession,
    run: _Run,
    unit_id: uuid.UUID,
    content_type: str,
    pinned: dict[str, Any],
) -> GeneratedContent | None:
    pinned_id = pinned.get(str(unit_id))
    if pinned_id:
        try:
            row = await session.get(GeneratedContent, uuid.UUID(str(pinned_id)))
        except ValueError:
            row = None
        if (
            row is not None
            and row.module_unit_id == unit_id
            and row.content_type == content_type
            and row.language == run.language
        ):
            return row
    return await select_unit_content_row(
        session, unit_id, content_type, run.language, run.level, run.country
    )


async def _previous_module(
    session: AsyncSession, module: Module, language: str
) -> dict[str, Any] | None:
    """The previous module of the course, with its plan's title and logline if any."""
    if module.course_id is None or module.module_number is None:
        return None
    previous = (
        await session.execute(
            select(Module.id, Module.module_number, Module.title_en, Module.title_fr)
            .where(
                Module.course_id == module.course_id,
                Module.module_number < module.module_number,
            )
            .order_by(Module.module_number.desc())
            .limit(1)
        )
    ).first()
    if previous is None:
        return None
    out: dict[str, Any] = {
        "number": previous.module_number,
        "module_title": _pair(previous.title_en, previous.title_fr),
    }
    row = await find_plan(session, previous.id, language)
    plan = (row.content or {}).get("plan") if row is not None else None
    if isinstance(plan, dict):
        out["logline"] = str(plan.get("logline") or "")
        title = plan.get("episode_title")
        if isinstance(title, dict):
            out["episode_title"] = title.get(language) or title.get("en")
    return out


async def _bible_modules(session: AsyncSession, module: Module) -> list[BibleModule]:
    """The course's modules, for the missions the bible writes."""
    if module.course_id is None:
        return [
            BibleModule(
                module.id, module.module_number or 1, _pair(module.title_en, module.title_fr)
            )
        ]
    rows = (
        await session.execute(
            select(Module.id, Module.module_number, Module.title_en, Module.title_fr).where(
                Module.course_id == module.course_id
            )
        )
    ).all()
    return [
        BibleModule(row.id, int(row.module_number or 0), _pair(row.title_en, row.title_fr))
        for row in rows
    ]


async def _chapter_rows(
    session: AsyncSession, language: str, units: Sequence[StoryUnit]
) -> dict[uuid.UUID | None, StoryCourseRecord]:
    lesson_ids = [u.module_unit_id for u in units if u.role == "lesson"]
    return {
        row.module_unit_id: row
        for row in (
            await session.execute(
                select(StoryCourseRecord).where(
                    StoryCourseRecord.module_unit_id.in_(lesson_ids),
                    StoryCourseRecord.language == language,
                )
            )
        ).scalars()
    }


def _usable_doc(row: StoryCourseRecord | None) -> dict[str, Any] | None:
    if row is None or row.status != "published" or not row.is_valid:
        return None
    return row.content


def _extras(
    rows: dict[uuid.UUID | None, StoryCourseRecord], lessons: Sequence[StoryUnit]
) -> dict[str, dict[str, Any]]:
    return {
        u.unit_number: dict(rows[u.module_unit_id].source_rows or {})
        for u in lessons
        if rows.get(u.module_unit_id) is not None
    }


def _steps(doc: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(doc, dict):
        return []
    return [
        step
        for chapter in doc.get("chapters") or []
        for scene in chapter.get("scenes") or []
        for step in scene.get("steps") or []
        if isinstance(step, dict)
    ]


def _props_seen(docs: dict[str, dict[str, Any] | None]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for unit, doc in docs.items():
        ids: set[str] = set()
        for chapter in (doc or {}).get("chapters") or []:
            for scene in chapter.get("scenes") or []:
                ids.update(scene.get("props") or [])
        for pid in ids:
            seen.setdefault(pid, []).append(unit)
    return seen


def _mcq_content(mcq: repair.QuizMcq) -> str:
    """All a pack reads of a course question: a changed explanation remakes the pack."""
    return sha(
        [
            mcq.stem,
            list(mcq.options),
            mcq.correct_index,
            mcq.explanation,
            list(mcq.option_misconceptions),
        ]
    )


def _plain(value: Any, limit: int) -> str:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return text[:limit]


def scene_summary(doc: dict[str, Any], language: str, *, last: bool) -> dict[str, Any] | None:
    """A chapter's last (or first) scene as the next writer reads it, in ``language``.

    ``{"place": title, "lines": ["narrator: ...", "{child}: ...", "[card: ...]",
    "[question]"]}``, at most the last (or first) 12 steps.
    """
    from app.ai.prompts.story_from_lesson import LAST_SCENE_LINES

    chapters = doc.get("chapters") or []
    scenes = [s for c in chapters for s in c.get("scenes") or []]
    if not scenes:
        return None
    scene = scenes[-1] if last else scenes[0]
    names = {m.get("id"): m.get("name") for m in doc.get("cast") or []}
    places = {p.get("id"): (p.get("title") or {}).get(language) for p in doc.get("places") or []}
    props = {p.get("id"): (p.get("label") or {}).get(language) for p in doc.get("props") or []}
    lines: list[str] = []
    for step in scene.get("steps") or []:
        kind = step.get("type")
        if kind == "narrate":
            lines.append(f"narrator: {step.get(language)}")
        elif kind == "say":
            lines.append(f"{names.get(step.get('who')) or step.get('who')}: {step.get(language)}")
        elif kind == "concept":
            lines.append(f"[card: {(step.get('title') or {}).get(language, '')}]")
        elif kind == "ask":
            lines.append("[question]")
        elif kind == "show" and step.get("visual") == "prop":
            label = props.get((step.get("params") or {}).get("prop"))
            lines.append(f"[close-up: {label}]")
        elif kind == "show":
            lines.append("[figure]")
        elif kind == "game":
            lines.append("[game]")
        elif kind == "photo":
            lines.append("[paper task]")
    lines = lines[-LAST_SCENE_LINES:] if last else lines[:LAST_SCENE_LINES]
    return {"place": places.get(scene.get("place")) or scene.get("place"), "lines": lines}
