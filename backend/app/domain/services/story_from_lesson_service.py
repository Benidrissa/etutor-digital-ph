"""Story mode for a lesson unit: generate once, validate, cache, serve.

The first time a learner opens a lesson's Story tab, the unit's own lesson and
quiz are turned into a ``story-course/1`` week and stored in ``story_courses``
bound to ``(module_unit_id, language)``. Every later learner gets the cached
week; the front end substitutes their first name for ``{child}``.

Pipeline (one Celery task, :func:`app.tasks.content_generation.generate_story_task`):

1. read the cached lesson row (generating it through the lesson service only
   when the unit has none) and the unit's quiz row, if any;
2. one model call for the *spine* (pedagogy and translations only);
3. :func:`app.domain.services.story_repair.build_story_document` — the
   deterministic layer that builds everything structural and normalises the
   spine;
4. :func:`validate_story_course` (Appendix C), plus the generator's own floor
   on the number of questions;
5. a bounded repair loop — at most :data:`MAX_REPAIR_CALLS` extra model calls,
   each told the remaining error codes and paths — then a salvage pass that
   drops model-authored items that still fail;
6. persist: published and valid, or a draft with its report (the API then
   answers 409 ``story_unavailable``). The validator's ``checks`` block is
   written into the stored document either way (C6).
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.usage_context import ai_usage_context
from app.api.v1.schemas.story_course import StoryCourse, ValidationIssue, ValidationReport
from app.domain.models.ai_usage_event import FEATURE_LESSON_GENERATION, FEATURE_STORY_GENERATION
from app.domain.models.content import GeneratedContent
from app.domain.models.module import Module
from app.domain.models.module_unit import ModuleUnit
from app.domain.models.story_course import StoryCourseRecord
from app.domain.services import story_repair as repair
from app.domain.services.story_course_validator import validate_story_course

logger = structlog.get_logger(__name__)

#: Extra model calls after the first one, each fed the remaining errors.
MAX_REPAIR_CALLS = 2

STORY_FEATURE_FLAG = "story-mode-feature-enabled"


def story_mode_enabled() -> bool:
    """The admin master switch; on by default."""
    from app.domain.services.platform_settings_service import SettingsCache

    return bool(SettingsCache.instance().get(STORY_FEATURE_FLAG, True))


# --------------------------------------------------------------------------
# Persistence shared with the authoring API
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class StoryBinding:
    """Which lesson unit a story tells, and which source rows it came from."""

    module_id: uuid.UUID
    module_unit_id: uuid.UUID
    language: str
    lesson_content_id: uuid.UUID
    lesson_revision: int
    quiz_content_id: uuid.UUID | None = None
    quiz_revision: int | None = None


async def upsert_story_course(
    db: AsyncSession,
    *,
    course: StoryCourse,
    content: dict[str, Any],
    report: ValidationReport,
    course_id: uuid.UUID | None,
    publish: bool,
    created_by: uuid.UUID | None = None,
    binding: StoryBinding | None = None,
) -> StoryCourseRecord:
    """Create or update the row for ``course.id`` (its slug). Does not commit.

    Shared by the authoring endpoint and the lesson-story generator so both
    write exactly the same columns. A hand-authored week that is saved
    without ``publish`` keeps a ``published`` status (the author is editing a
    live week); a lesson story that is not publishable is always demoted to
    ``draft``, so an invalid regeneration can never be served.
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

    if binding is not None:
        record.module_id = binding.module_id
        record.module_unit_id = binding.module_unit_id
        record.language = binding.language
        record.source_lesson_content_id = binding.lesson_content_id
        record.source_lesson_revision = binding.lesson_revision
        record.source_quiz_content_id = binding.quiz_content_id
        record.source_quiz_revision = binding.quiz_revision
    return record


async def find_unit_story(
    session: AsyncSession, module_unit_id: uuid.UUID, language: str
) -> StoryCourseRecord | None:
    return (
        await session.execute(
            select(StoryCourseRecord).where(
                StoryCourseRecord.module_unit_id == module_unit_id,
                StoryCourseRecord.language == language,
            )
        )
    ).scalar_one_or_none()


async def story_sources_are_fresh(session: AsyncSession, record: StoryCourseRecord) -> bool:
    """Whether the lesson and quiz a story was derived from are unchanged.

    Stale when the lesson row is gone or regenerated (``content_revision``
    moved), when the quiz row is gone or regenerated, or — for a story built
    before the unit had a quiz — as soon as the unit has one, so the story's
    questions come to be derived from it. Hand-authored weeks are never stale.
    """
    if record.module_unit_id is None:
        return True
    if record.source_lesson_content_id is None or record.source_lesson_revision is None:
        return False

    ids = [record.source_lesson_content_id]
    if record.source_quiz_content_id is not None:
        ids.append(record.source_quiz_content_id)
    revisions = {
        row_id: (revision or 1)
        for row_id, revision in (
            await session.execute(
                select(GeneratedContent.id, GeneratedContent.content_revision).where(
                    GeneratedContent.id.in_(ids)
                )
            )
        ).all()
    }
    if revisions.get(record.source_lesson_content_id) != record.source_lesson_revision:
        return False
    if record.source_quiz_revision is not None:
        return (
            record.source_quiz_content_id is not None
            and revisions.get(record.source_quiz_content_id) == record.source_quiz_revision
        )
    quiz_now = (
        await session.execute(
            select(GeneratedContent.id)
            .where(
                GeneratedContent.module_unit_id == record.module_unit_id,
                GeneratedContent.content_type == "quiz",
                GeneratedContent.language == record.language,
            )
            .limit(1)
        )
    ).first()
    return quiz_now is None


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
    return repair.publishable(validate_story_course(course), doc)


@dataclass
class StoryGeneration:
    doc: dict[str, Any]
    report: ValidationReport
    model_calls: int
    salvaged: bool = False
    dropped: dict[str, list[str]] = field(default_factory=dict)


def build_context(
    module: Module,
    unit: ModuleUnit,
    language: str,
    lesson_content: dict[str, Any],
    quiz_row: GeneratedContent | None,
) -> repair.LessonStoryContext:
    """Everything the deterministic layer needs, read once from the ORM rows."""
    from app.ai.prompts.audience import detect_audience

    def pair(en: str | None, fr: str | None) -> dict[str, str]:
        en, fr = (en or "").strip(), (fr or "").strip()
        return {"en": en or fr, "fr": fr or en}

    course = module.course
    mcqs: list[repair.QuizMcq] = []
    if quiz_row is not None:
        mcqs, _dropped = repair.parse_quiz_mcqs((quiz_row.content or {}).get("questions"))
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
        is_kids=detect_audience(course).is_kids,
    )


class StoryFromLessonService:
    """Generates and caches the story mode of one lesson unit."""

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

    async def _call_model(self, system_prompt: str, user_message: str) -> dict[str, Any] | None:
        """One spine call; ``None`` when the answer could not be read as JSON."""
        try:
            spine = await self.claude_service.generate_structured_content(
                system_prompt, user_message, "story"
            )
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

    async def generate_document(
        self, ctx: repair.LessonStoryContext, *, system_prompt: str
    ) -> StoryGeneration:
        """Spine call → deterministic build → validate → bounded repair → salvage.

        Database-free, so the whole pipeline can be tested with a fake model.
        Returns the best document seen (fewest errors), with the validator's
        ``checks`` written into it.
        """
        from app.ai.prompts.story_from_lesson import (
            build_repair_message,
            build_story_user_message,
        )

        user_message = build_story_user_message(ctx)
        budget = 1 + self.max_repair_calls
        best: tuple[dict[str, Any], repair.StoryBuild, ValidationReport] | None = None
        feedback_spine: dict[str, Any] | None = None
        issues: list[ValidationIssue] = []
        calls = 0

        with ai_usage_context(FEATURE_STORY_GENERATION, only_if_unset=True):
            for attempt in range(budget):
                message = (
                    user_message
                    if attempt == 0
                    else build_repair_message(user_message, issues, feedback_spine, attempt, budget)
                )
                calls += 1
                spine = await self._call_model(system_prompt, message)
                build = repair.build_story_document(ctx, spine or {})
                report = validate_document(build.doc)
                logger.info(
                    "Story attempt validated",
                    slug=ctx.slug,
                    attempt=attempt + 1,
                    readable=spine is not None,
                    errors=len(report.errors),
                    warnings=len(report.warnings),
                )
                if best is None or len(report.errors) < len(best[2].errors):
                    best = (spine or {}, build, report)
                if report.ok:
                    break
                if spine is not None:
                    feedback_spine, issues = spine, list(report.errors)
                else:
                    issues = []

        assert best is not None
        spine, build, report = best
        generation = StoryGeneration(doc=build.doc, report=report, model_calls=calls)
        if not report.ok:
            salvaged = self._salvage(ctx, spine, build, report)
            if salvaged is not None:
                generation = salvaged
                generation.model_calls = calls

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
        rebuilt = repair.build_story_document(
            ctx,
            spine,
            drop_question_ids=questions,
            drop_exercise_ids=exercises,
            drop_minigame=minigame,
        )
        rebuilt_report = validate_document(rebuilt.doc)
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
            dropped={"questions": sorted(questions), "exercises": sorted(exercises)},
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
    ) -> StoryCourseRecord:
        """Return the unit's story, generating and caching it when needed.

        A cached story is returned as-is while its sources are fresh — valid or
        not, so a story that could not be made valid is not regenerated (and
        paid for) on every view; it is retried when the lesson or quiz changes,
        or when an admin forces it.
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

        existing = await find_unit_story(session, unit.id, language)
        if (
            existing is not None
            and not force_regenerate
            and await story_sources_are_fresh(session, existing)
        ):
            return existing

        lesson_row = await self._lesson_row(session, module, unit, language, level, country)
        quiz_row = await select_unit_content_row(
            session, unit.id, "quiz", language, lesson_row.level, lesson_row.country_context
        )
        ctx = build_context(module, unit, language, lesson_row.content or {}, quiz_row)

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
        )
        return await self._persist(session, generation, binding, module.course_id)

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
