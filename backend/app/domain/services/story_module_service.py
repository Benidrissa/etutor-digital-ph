"""One story per module: chapters made, cached and joined (contract C-3).

A module story is one ``story-course/1`` week per ``(module, language)``,
stored in ``story_courses`` with ``module_id`` set and no unit (migration
107). It has one chapter per unit of the module, in teaching order:

* a **lesson** unit's chapter is that lesson's own story, made and cached by
  the per-lesson pipeline (:class:`StoryFromLessonService`, contract C-1) as
  a chapter row bound to the unit;
* a **quiz** or **case-study** unit's chapter is a short deterministic
  checkpoint scene that sends the learner to the unit's page.

:func:`story_module_assembly.assemble_module_story` (contract C-2) joins the
chapters without a model call. So a module story costs its chapters and
nothing more, and only a changed chapter is ever paid for again.

Generation (:meth:`ModuleStoryService.get_or_generate_module_story`, run by
:func:`app.tasks.content_generation.generate_module_story_task`) runs in one
asyncio loop:

1. read the module's units (:func:`load_story_units`) and their chapter rows;
   a fresh module story is returned as it is;
2. for every lesson whose chapter is missing or stale, concurrently (at most
   ``concurrency`` at a time, each in its own ``AsyncSession``): generate the
   lesson if the unit has none (then dispatch its quality assessment, as the
   lesson task does), generate the covering quiz unit's quiz if it has none —
   at most once per quiz unit — and make the chapter, which commits its row;
3. if any chapter failed, raise :class:`ChapterGenerationFailed`: the module
   row is neither written nor updated, and the chapters that succeeded stay
   cached, so the next open makes only the rest;
4. otherwise assemble, validate (:func:`validate_module_story`) and store the
   module row with its manifest. A module story that does not validate is
   stored as a draft (the API answers 409) and is never sent to a model.

A Celery soft time limit inside a chapter cancels every other chapter and
propagates bare (an :class:`asyncio.TaskGroup` wraps it; ``gather`` with
``return_exceptions=True`` would have swallowed it).

Freshness (:func:`module_story_is_fresh`) needs no model and three queries
however many chapters there are: the roster, the chapter rows, and one query
of every chapter's sources. A module story is stale when the assembler
version, the roster digest or any lesson's chapter row (id and
``updated_at``) differs from its manifest, or when any of those chapters is
stale itself. A roster or title change therefore only re-merges: no model call.
"""

from __future__ import annotations

import asyncio
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
from app.domain.models.ai_usage_event import FEATURE_LESSON_GENERATION, FEATURE_QUIZ_GENERATION
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services.story_from_lesson_service import (
    MAX_REPAIR_CALLS,
    ModuleStoryBinding,
    StoryFromLessonService,
    _unit_order,
    chapters_are_fresh,
    content_digest,
    covering_quiz_units,
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

logger = structlog.get_logger(__name__)

#: Lesson chapters made at the same time, each with its own database session.
DEFAULT_CONCURRENCY = 6


def story_dispatch_key(module_id: uuid.UUID, language: str) -> str:
    """Redis key holding the id of the task generating a module's story in ``language``."""
    return f"story_dispatch:module:{module_id}:{language}"


class NoStoryContent(ValueError):
    """The module has no lesson unit, so there is nothing to tell."""


class ChapterGenerationFailed(Exception):
    """Some lesson chapters could not be made; the module story was not written.

    ``failed_units`` are their unit numbers, in teaching order. The chapters
    that were made are cached, so the next attempt makes only these.
    """

    def __init__(self, failed_units: list[str], errors: dict[str, str] | None = None) -> None:
        super().__init__(f"Story chapters failed for units {', '.join(failed_units)}")
        self.failed_units = failed_units
        self.errors = dict(errors or {})


class CoveringQuizUnavailable(RuntimeError):
    """The quiz of the quiz unit covering a lesson could not be generated."""


class ModuleStoryAssemblyFailed(RuntimeError):
    """The assembled module story does not even parse: an assembler bug."""


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
class _ChapterState:
    """A lesson unit's chapter row as freshness sees it (``content`` not loaded)."""

    story_id: uuid.UUID
    updated_at: datetime | None
    fresh: bool


async def _chapter_states(
    session: AsyncSession, units: Sequence[StoryUnit], language: str
) -> dict[uuid.UUID, _ChapterState]:
    """Every lesson unit's chapter row and whether it is fresh — two queries.

    The chapter documents are not loaded: their builder version is read in
    SQL, and every chapter's sources are checked in one query
    (:func:`chapters_are_fresh`).
    """
    lesson_ids = [u.module_unit_id for u in units if u.role == "lesson"]
    if not lesson_ids:
        return {}
    rows = (
        await session.execute(
            select(StoryCourseRecord, StoryCourseRecord.content["sira_builder"].label("builder"))
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
    fresh = await chapters_are_fresh(
        session,
        records,
        builders=[row.builder for row in rows],
        covering=covering_quiz_units(_roster(units)),
    )
    return {
        record.module_unit_id: _ChapterState(record.id, record.updated_at, is_fresh)
        for record, is_fresh in zip(records, fresh, strict=True)
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
) -> bool:
    """Whether ``record`` was merged from exactly this roster and these fresh chapters."""
    manifest = record.source_rows
    if not _is_module_row(record) or not isinstance(manifest, dict):
        return False
    if manifest.get("assembler") != MODULE_ASSEMBLER_VERSION:
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


async def module_story_is_fresh(session: AsyncSession, record: StoryCourseRecord) -> bool:
    """Whether a module story row can be served as it is — three queries, no model.

    Stale when it is not a module row, was built by another assembler
    version, the module's roster changed (:func:`roster_digest`), a lesson's
    chapter row is not the one (id and ``updated_at``) its manifest records,
    or any of those chapters is stale (:func:`chapters_are_fresh`, one batched
    query for all of them).
    """
    if not _is_module_row(record) or not isinstance(record.source_rows, dict):
        return False
    module_id, language = record.module_id, record.language
    if module_id is None or language is None:
        return False
    if record.source_rows.get("assembler") != MODULE_ASSEMBLER_VERSION:
        return False
    units = await load_story_units(session, module_id)
    if record.source_units_digest != roster_digest(units):
        return False
    states = await _chapter_states(session, units, language)
    return _module_story_matches(record, units, states)


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------


@dataclass
class _Run:
    """One generation of a module story: its inputs and what the chapters share."""

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
    quiz_locks: dict[uuid.UUID, asyncio.Lock] = field(default_factory=dict)
    quiz_ready: set[uuid.UUID] = field(default_factory=set)
    quiz_failed: dict[uuid.UUID, str] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)


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
    """Makes, caches and serves the story of a module (contract C-3)."""

    def __init__(
        self,
        claude_service: Any,
        lesson_service: Any,
        quiz_service: Any,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_repair_calls: int = MAX_REPAIR_CALLS,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        self.lesson_service = lesson_service
        self.quiz_service = quiz_service
        self.concurrency = concurrency
        # No lesson service of its own: every missing lesson is generated by
        # _ensure_lesson first, with its assessment dispatched.
        self.chapters = StoryFromLessonService(
            claude_service, lesson_service=None, max_repair_calls=max_repair_calls
        )

    async def get_or_generate_module_story(
        self,
        module_id: uuid.UUID,
        language: str,
        session_factory: Callable[[], Any],
        *,
        level: int = 1,
        country: str = "CI",
        force_regenerate: bool = False,
    ) -> StoryCourseRecord:
        """Return the module story, making the missing or stale chapters first.

        ``session_factory()`` must give a new ``AsyncSession`` (an async
        context manager) per call: every chapter gets its own, and none is
        open across the fan-out but the chapters'. ``level`` and ``country``
        only choose which missing lesson or quiz is generated and which cached
        row a chapter prefers. ``force_regenerate`` remakes every chapter (not
        the lessons or quizzes).

        Raises ``ValueError`` for an unknown module, :class:`NoStoryContent`
        when the module has no lesson unit, :class:`ChapterGenerationFailed`
        when a chapter could not be made (nothing is written for the module),
        and lets ``SoftTimeLimitExceeded`` through.
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
            states = await _chapter_states(session, units, language)
            existing = await find_module_story(session, module_id, language)
            if (
                existing is not None
                and not force_regenerate
                and _module_story_matches(existing, units, states)
            ):
                return existing
            ctx = await self._context(session, module, language)
            course_id = module.course_id

        stale = [
            u
            for u in lessons
            if force_regenerate
            or u.module_unit_id not in states
            or not states[u.module_unit_id].fresh
        ]
        logger.info(
            "Module story: making chapters",
            module_id=str(module_id),
            language=language,
            lessons=len(lessons),
            chapters_to_make=[u.unit_number for u in stale],
            force=force_regenerate,
        )
        if stale:
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
            )
            await self._make_chapters(run, stale)
            if run.failures:
                failed = [u.unit_number for u in stale if u.unit_number in run.failures]
                logger.warning(
                    "Module story not written: chapters failed",
                    module_id=str(module_id),
                    language=language,
                    failed_units=failed,
                )
                raise ChapterGenerationFailed(failed, run.failures)

        return await self._merge(session_factory, ctx, units, course_id)

    # -- context ------------------------------------------------------------

    @staticmethod
    async def _context(session: AsyncSession, module: Module, language: str) -> ModuleStoryContext:
        from app.ai.prompts.audience import detect_audience

        course = module.course
        previous = None
        if module.course_id is not None and module.module_number is not None:
            previous = (
                await session.execute(
                    select(Module.module_number, Module.title_en, Module.title_fr)
                    .where(
                        Module.course_id == module.course_id,
                        Module.module_number < module.module_number,
                    )
                    .order_by(Module.module_number.desc())
                    .limit(1)
                )
            ).first()
        return ModuleStoryContext(
            module_id=module.id,
            language=language,
            module_number=module.module_number or 1,
            module_title=_pair(module.title_en, module.title_fr),
            course_title=_pair(course.title_en, course.title_fr) if course else _pair("", ""),
            previous_module=(
                (previous.module_number, _pair(previous.title_en, previous.title_fr))
                if previous is not None
                else None
            ),
            is_kids=detect_audience(course).is_kids,
        )

    # -- the chapters -------------------------------------------------------

    async def _make_chapters(self, run: _Run, stale: Sequence[StoryUnit]) -> None:
        try:
            async with asyncio.TaskGroup() as group:
                for unit in stale:
                    group.create_task(
                        self._chapter(run, unit), name=f"story-chapter-{unit.unit_number}"
                    )
        except* SoftTimeLimitExceeded as limit:
            # The TaskGroup has cancelled every other chapter; the Celery task
            # must see the time limit itself, not a group wrapping it.
            raise limit.exceptions[0] from None

    async def _chapter(self, run: _Run, unit: StoryUnit) -> None:
        """Make one lesson's chapter in its own session; record, never raise, a failure."""
        try:
            async with run.semaphore, run.session_factory() as session:
                await self._ensure_lesson(run, session, unit)
                # Release the connection before waiting on another chapter's quiz.
                await session.rollback()
                await self._ensure_quiz(run, session, unit)
                await self.chapters.get_or_generate_unit_story(
                    run.module_id,
                    unit.unit_number,
                    run.language,
                    session,
                    level=run.level,
                    country=run.country,
                    force_regenerate=run.force,
                )
        except SoftTimeLimitExceeded:
            raise
        except Exception as exc:
            run.failures[unit.unit_number] = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning(
                "Module story chapter failed",
                module_id=str(run.module_id),
                language=run.language,
                unit=unit.unit_number,
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )

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

    async def _ensure_quiz(self, run: _Run, session: AsyncSession, unit: StoryUnit) -> None:
        """Generate the covering quiz unit's quiz when it has none — once per quiz unit.

        The chapters covered by the same quiz unit wait for the first one to
        generate it, then build from it; if it fails, they all fail (a chapter
        built without the quiz would be paid for again once it exists). A
        covering unit that is really a case study (#2163) never gets a quiz.
        """
        quiz_unit_id = run.covering.get(unit.module_unit_id)
        if quiz_unit_id is None or self.quiz_service is None:
            return
        quiz_unit = run.units[quiz_unit_id]
        if quiz_unit.role != "quiz_checkpoint":
            return
        lock = run.quiz_locks.setdefault(quiz_unit_id, asyncio.Lock())
        async with lock:
            if quiz_unit_id in run.quiz_failed:
                raise CoveringQuizUnavailable(
                    f"The quiz of unit {quiz_unit.unit_number} could not be generated"
                    f" ({run.quiz_failed[quiz_unit_id]})"
                )
            if quiz_unit_id in run.quiz_ready:
                return
            if await _has_content(session, quiz_unit_id, "quiz", run.language):
                run.quiz_ready.add(quiz_unit_id)
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
                run.quiz_failed[quiz_unit_id] = type(exc).__name__
                raise CoveringQuizUnavailable(
                    f"The quiz of unit {quiz_unit.unit_number} could not be generated"
                ) from exc
            run.quiz_ready.add(quiz_unit_id)
            logger.info(
                "Quiz generated for module story chapters",
                module_id=str(run.module_id),
                quiz_unit=quiz_unit.unit_number,
                language=run.language,
                content_id=str(getattr(quiz, "id", "")),
            )

    # -- the module row -----------------------------------------------------

    async def _merge(
        self,
        session_factory: Callable[[], Any],
        ctx: ModuleStoryContext,
        units: Sequence[StoryUnit],
        course_id: uuid.UUID | None,
    ) -> StoryCourseRecord:
        """Assemble the cached chapters, validate, and store the module row."""
        async with session_factory() as session:
            lesson_ids = [u.module_unit_id for u in units if u.role == "lesson"]
            rows = {
                row.module_unit_id: row
                for row in (
                    await session.execute(
                        select(StoryCourseRecord).where(
                            StoryCourseRecord.module_unit_id.in_(lesson_ids),
                            StoryCourseRecord.language == ctx.language,
                        )
                    )
                ).scalars()
            }
            sources: list[ChapterSource] = []
            chapter_rows: list[StoryCourseRecord | None] = []
            for unit in units:
                row = rows.get(unit.module_unit_id) if unit.role == "lesson" else None
                usable = row is not None and row.status == "published" and bool(row.is_valid)
                chapter_doc = row.content if row is not None and usable else None
                sources.append(ChapterSource(unit=unit, doc=chapter_doc))
                chapter_rows.append(row)

            doc = assemble_module_story(ctx, sources)
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
            manifest = {"assembler": MODULE_ASSEMBLER_VERSION, "units": entries}
            statuses = [entry["status"] for entry in entries]
            if not report.ok:
                # Valid chapters that do not merge into a valid story are an
                # assembler bug; with no chapter ready it is just too thin.
                log = logger.error if "ready" in statuses else logger.warning
                log(
                    "Module story is not publishable; stored as a draft",
                    module_id=str(ctx.module_id),
                    language=ctx.language,
                    codes=sorted({issue.code for issue in report.errors}),
                    statuses=statuses,
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


def _chapter_status(doc: dict[str, Any], index: int, source: ChapterSource) -> str:
    """The status the assembler gave chapter ``index`` (its ``covers``)."""
    chapters = doc.get("chapters")
    if isinstance(chapters, list) and index < len(chapters):
        covers = chapters[index].get("covers") if isinstance(chapters[index], dict) else None
        if (
            isinstance(covers, dict)
            and covers.get("module_unit_id") == str(source.unit.module_unit_id)
            and covers.get("status") in ("ready", "unavailable", "checkpoint")
        ):
            return str(covers["status"])
    if source.unit.role != "lesson":
        return "checkpoint"
    return "ready" if source.doc is not None else "unavailable"
