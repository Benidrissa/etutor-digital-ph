#!/usr/bin/env python3
"""List or generate the story of chosen modules, from the server.

Story mode tells each module as one story: one chapter per lesson, then a
final rally for the module's quiz, told by the course's cast (#2674). It is
normally generated the first time a learner opens it from the module page.
This script lets an operator do it ahead of time for chosen courses, through
the very same path: it dispatches ``generate_module_story_task`` through the
API's own dispatch (``dispatch_module_story_generation``, with its dedup key,
so it joins a generation a learner already started rather than paying for a
second one), waits for the worker, then prints what was stored.

Usage (inside the backend container)::

    # Which courses match; for module 1 of each: its units and their roles,
    # the cached lessons, quizzes and case studies, the lesson chapters and
    # the module story
    python scripts/generate_lesson_stories.py list --query biolog --query math

    # Generate the story of module 1 of each course, in French and English
    python scripts/generate_lesson_stories.py generate \
        --course <slug-or-uuid> --course <slug-or-uuid> --language fr --language en

    # Generate what a request file asks for (run after every deploy)
    python scripts/generate_lesson_stories.py requests scripts/story_requests.json

    # ... and keep the plan and every chapter as JSON (a recorded regression
    # fixture of real model output, #2680)
    python scripts/generate_lesson_stories.py requests scripts/story_requests.json \
        --dump /tmp/story-dump

After each story the script prints the episode plan's logline and titles,
the full transcript of the story (who says what, the cards, the questions,
the close-ups) and each chapter's ``checks.story_quality``, so a workflow log
is enough to judge whether it sounds like a story.

``generate`` and ``requests`` exit non-zero unless every module story ended up
valid and published. Re-running them is cheap: a module story that is already
cached and fresh is returned as it is, with no model call, and a stale one
pays only for the chapters whose lesson or quiz changed. A first run also
generates the module's missing lessons and quizzes, so it can take a while.

The file keeps its old name (it once made one lesson's story): the deploy
workflow runs from ``main`` while this script runs from the deployed image.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, or_, select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.ai.prompts.audience import detect_audience  # noqa: E402
from app.domain.models.content import GeneratedContent  # noqa: E402
from app.domain.models.course import Course  # noqa: E402
from app.domain.models.module import Module  # noqa: E402
from app.domain.models.story_course import StoryCourseRecord  # noqa: E402
from app.domain.services.story_from_lesson_service import chapters_are_fresh  # noqa: E402
from app.domain.services.story_module_assembly import StoryUnit  # noqa: E402
from app.domain.services.story_module_service import (  # noqa: E402
    find_module_story,
    load_story_units,
    module_story_is_fresh,
)
from app.domain.services.story_plan import find_plan  # noqa: E402

LANGUAGES = ("fr", "en")
_FINISHED_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})
#: Long enough for a first run that also generates the module's lessons and quizzes, and
#: under the deploy workflow's 60-minute SSH command timeout (a continuation is followed).
DEFAULT_TIMEOUT_S = 3300
LESSON_INDEX_IGNORED = "lesson_index is ignored; a story covers a whole module"


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


@dataclass(frozen=True)
class ModuleTarget:
    """One course's chosen module and its units in teaching order, with their roles."""

    course: Course
    module: Module
    units: tuple[StoryUnit, ...]

    @property
    def lessons(self) -> list[StoryUnit]:
        return [unit for unit in self.units if unit.role == "lesson"]


# -- lookups -----------------------------------------------------------------


async def find_courses(session, queries: list[str]) -> list[Course]:
    """Courses whose slug or French/English title contains any of ``queries``."""
    clauses = []
    for query in queries:
        pattern = f"%{query}%"
        clauses += [
            Course.slug.ilike(pattern),
            Course.title_fr.ilike(pattern),
            Course.title_en.ilike(pattern),
        ]
    if not clauses:
        return []
    rows = await session.execute(select(Course).where(or_(*clauses)).order_by(Course.title_fr))
    return list(rows.scalars().all())


async def resolve_course(session, ref: str) -> Course | None:
    """A course by UUID or slug."""
    try:
        course_id = uuid.UUID(ref)
    except ValueError:
        course_id = None
    if course_id is not None:
        found = await session.get(Course, course_id)
        if found is not None:
            return found
    rows = await session.execute(select(Course).where(Course.slug == ref))
    return rows.scalar_one_or_none()


async def module_target(
    session,
    course: Course,
    module_index: int,
    module_id: uuid.UUID | None = None,
) -> tuple[ModuleTarget | None, str]:
    """The ``module_index``-th module of the course by number (or the module
    ``module_id``), with its units in teaching order and their story roles
    (:func:`load_story_units`)."""
    modules = list(
        (
            await session.execute(
                select(Module).where(Module.course_id == course.id).order_by(Module.module_number)
            )
        )
        .scalars()
        .all()
    )
    if module_id is not None:
        module = next((m for m in modules if m.id == module_id), None)
        if module is None:
            return None, f"module {module_id} is not in the course"
    elif len(modules) < module_index:
        return None, f"the course has {len(modules)} module(s)"
    else:
        module = modules[module_index - 1]
    units = await load_story_units(session, module.id)
    return ModuleTarget(course, module, tuple(units)), ""


async def cached_rows(session, unit_ids: list[uuid.UUID]) -> dict[tuple, int]:
    """``{(module_unit_id, content_type, language): count}`` of cached content."""
    if not unit_ids:
        return {}
    rows = await session.execute(
        select(
            GeneratedContent.module_unit_id,
            GeneratedContent.content_type,
            GeneratedContent.language,
            func.count(),
        )
        .where(GeneratedContent.module_unit_id.in_(unit_ids))
        .group_by(
            GeneratedContent.module_unit_id,
            GeneratedContent.content_type,
            GeneratedContent.language,
        )
    )
    return {(r[0], r[1], r[2]): r[3] for r in rows.all()}


async def chapter_rows(session, unit_ids: list[uuid.UUID]) -> dict[tuple, StoryCourseRecord]:
    """``{(module_unit_id, language): chapter row}`` of the given lesson units."""
    if not unit_ids:
        return {}
    rows = await session.execute(
        select(StoryCourseRecord).where(StoryCourseRecord.module_unit_id.in_(unit_ids))
    )
    return {(r.module_unit_id, r.language): r for r in rows.scalars().all()}


# -- reporting ---------------------------------------------------------------


def story_summary(record: StoryCourseRecord | None) -> dict[str, Any]:
    """What an operator needs to judge one stored lesson chapter."""
    if record is None:
        return {"stored": False}
    report = record.validation_report or {}
    content = record.content or {}
    sources = content.get("sources") or []
    return {
        "stored": True,
        "slug": record.slug,
        "status": record.status,
        "is_valid": bool(record.is_valid),
        "max_points": record.max_points,
        "questions": len(content.get("questions") or []),
        "exercises": len(content.get("exercises") or []),
        "questions_from_quiz": any(
            isinstance(s, dict) and s.get("kind") == "test" for s in sources
        ),
        "source_quiz_content_id": (
            str(record.source_quiz_content_id) if record.source_quiz_content_id else None
        ),
        "errors": [i.get("code") for i in report.get("errors") or []],
        "warnings": [i.get("code") for i in report.get("warnings") or []],
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def module_story_summary(record: StoryCourseRecord | None) -> dict[str, Any]:
    """What an operator needs to judge one stored module story.

    The chapter counts come from its manifest (``source_rows``): one entry per
    unit, ``ready`` (a lesson's chapter), ``unavailable`` (a lesson whose
    chapter could not be made valid: a "read it on its page" placeholder) or
    ``checkpoint`` (a quiz or case-study unit, which has no chapter of its
    own). ``rally`` is the status of the final rally chapter (``ready``,
    ``draft``: left out until its inputs change, ``none``: no quiz to mix), or
    ``None`` for a module without a quiz unit.
    """
    if record is None:
        return {"stored": False}
    report = record.validation_report or {}
    content = record.content or {}
    manifest = record.source_rows if isinstance(record.source_rows, dict) else {}
    entries = [e for e in manifest.get("units") or [] if isinstance(e, dict)]
    statuses = [e.get("status") for e in entries]
    module_story = content.get("module_story") if isinstance(content, dict) else None
    return {
        "stored": True,
        "slug": record.slug,
        "status": record.status,
        "is_valid": bool(record.is_valid),
        "max_points": record.max_points,
        "chapters": len(content.get("chapters") or []),
        "ready": statuses.count("ready"),
        "unavailable": statuses.count("unavailable"),
        "checkpoint": statuses.count("checkpoint"),
        "rally": (manifest.get("rally") or {}).get("status")
        if isinstance(manifest.get("rally"), dict)
        else None,
        "unavailable_units": [
            e.get("unit_number") for e in entries if e.get("status") == "unavailable"
        ],
        "questions": len(content.get("questions") or []),
        "exercises": len(content.get("exercises") or []),
        "revision": module_story.get("revision") if isinstance(module_story, dict) else None,
        "errors": [i.get("code") for i in report.get("errors") or []],
        "warnings": [i.get("code") for i in report.get("warnings") or []],
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def story_excerpt(content: dict[str, Any] | None, limit: int = 12) -> list[str]:
    """A few lines to judge a module story by from a log: its title, each
    chapter with the unit it covers, and question prompts, in the language it
    teaches in. The learner's name is still the ``{child}`` placeholder in a
    stored story."""
    if not isinstance(content, dict):
        return []
    language = (content.get("languages") or {}).get("target") or "fr"

    def text(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get(language) or next(iter(value.values()), "")
        return " ".join(str(value or "").split())[:160]

    lines = [f"title: {text(content.get('title'))}"]
    for chapter in (content.get("chapters") or [])[:limit]:
        if not isinstance(chapter, dict):
            continue
        covers = chapter.get("covers") if isinstance(chapter.get("covers"), dict) else {}
        unit = " ".join(
            str(covers[key]) for key in ("unit_number", "role", "status") if covers.get(key)
        )
        lines.append(f"chapter {unit or '?'}: {text(chapter.get('title'))}")
    for question in (content.get("questions") or [])[:limit]:
        if isinstance(question, dict):
            lines.append(f"{question.get('id', '?')}: {text(question.get('prompt'))}")
    return lines


def print_chapter(prefix: str, summary: dict[str, Any], fresh: bool | None) -> None:
    if not summary.get("stored"):
        print(f"{prefix}chapter: none")
        return
    print(
        f"{prefix}chapter: {summary['slug']} status={summary['status']} "
        f"valid={summary['is_valid']} fresh={fresh} questions={summary['questions']} "
        f"from_quiz={summary['questions_from_quiz']}"
    )


def print_module_summary(prefix: str, summary: dict[str, Any], fresh: bool | None = None) -> None:
    if not summary.get("stored"):
        print(f"{prefix}module story: none")
        return
    freshness = "" if fresh is None else f" fresh={fresh}"
    print(
        f"{prefix}module story: {summary['slug']} status={summary['status']} "
        f"valid={summary['is_valid']}{freshness} chapters={summary['chapters']} "
        f"(ready={summary['ready']} unavailable={summary['unavailable']} "
        f"checkpoint={summary['checkpoint']}) questions={summary['questions']} "
        f"max_points={summary['max_points']} revision={summary['revision']}"
    )
    if summary["unavailable_units"]:
        print(f"{prefix}  unavailable units={summary['unavailable_units']}")
    if summary.get("rally"):
        print(f"{prefix}  rally={summary['rally']}")
    print(f"{prefix}  errors={summary['errors'] or 'none'}")
    print(f"{prefix}  warnings={summary['warnings'] or 'none'}")


# -- commands ----------------------------------------------------------------


async def cmd_list(session_factory, queries: list[str], module_index: int) -> int:
    async with session_factory() as session:
        courses = await find_courses(session, queries)
        if not courses:
            print(f"No course matches {queries!r}.")
            return 1
        for course in courses:
            audience = detect_audience(course)
            print("=" * 72)
            print(f"{course.title_fr} / {course.title_en}")
            print(
                f"  id={course.id} slug={course.slug} status={course.status} "
                f"kids={audience.is_kids}"
            )
            target, why = await module_target(session, course, module_index)
            if target is None:
                print(f"  no module {module_index}: {why}")
                continue
            print(
                f"  module {target.module.module_number}: {target.module.title_fr} "
                f"(id={target.module.id}) units={len(target.units)} "
                f"lessons={len(target.lessons)}"
            )
            counts = await cached_rows(session, [u.module_unit_id for u in target.units])
            chapters = await chapter_rows(session, [u.module_unit_id for u in target.lessons])
            records = list(chapters.values())
            fresh = dict(
                zip(
                    chapters.keys(),
                    await chapters_are_fresh(session, records) if records else [],
                    strict=True,
                )
            )
            for unit in target.units:
                print(
                    f"    {unit.unit_number} {unit.role} (type={unit.unit_type}) {unit.title['fr']}"
                )
                for language in LANGUAGES:
                    cached = " ".join(
                        f"{kind}={counts.get((unit.module_unit_id, kind, language), 0)}"
                        for kind in ("lesson", "quiz", "case")
                    )
                    print(f"      [{language}] cached {cached}")
                    if unit.role == "lesson":
                        key = (unit.module_unit_id, language)
                        print_chapter(
                            f"      [{language}] ",
                            story_summary(chapters.get(key)),
                            fresh.get(key),
                        )
            for language in LANGUAGES:
                record = await find_module_story(session, target.module.id, language)
                is_fresh = (
                    await module_story_is_fresh(session, record, units=target.units)
                    if record is not None
                    else None
                )
                print_module_summary(f"  [{language}] ", module_story_summary(record), is_fresh)
    return 0


async def wait_for_task(task_id: str, timeout_s: int, poll_s: float = 5.0) -> tuple[str, Any]:
    """Poll a Celery task until it finishes or ``timeout_s`` passes.

    A module story run that reached its deadline hands over to a continuation
    (``continued_by``, #2680): that task is followed, within the same timeout.
    """
    from celery.result import AsyncResult

    waited = 0.0
    while True:
        result = AsyncResult(task_id)
        state = result.state
        if state in _FINISHED_STATES:
            value = result.result
            following = value.get("continued_by") if isinstance(value, dict) else None
            if state == "SUCCESS" and following:
                print(f"  task {task_id} continues in {following}")
                task_id = str(following)
                continue
            return state, value
        if waited >= timeout_s:
            return f"TIMEOUT({state})", None
        await asyncio.sleep(poll_s)
        waited += poll_s


# -- the transcript -------------------------------------------------------------


def _text(value: Any, language: str) -> str:
    if isinstance(value, dict):
        value = value.get(language) or next(iter(value.values()), "")
    return " ".join(str(value or "").split())


def story_transcript(
    content: dict[str, Any] | None, plan: dict[str, Any] | None = None
) -> list[str]:
    """The whole story as it plays, in the language it teaches in (#2680).

    The plan's logline and titles first, then every chapter: each scene's
    place and cast, who says what (with the mood), the narration, the cards,
    the questions, the close-ups, the game and the paper tasks. The learner's
    name is still the ``{child}`` placeholder in a stored story.
    """
    if not isinstance(content, dict):
        return []
    language = (content.get("languages") or {}).get("target") or "fr"
    lines: list[str] = []
    if isinstance(plan, dict):
        lines.append(f"EPISODE «{_text(plan.get('episode_title'), language)}»")
        lines.append(f"LOGLINE: {_text(plan.get('logline'), 'en')}")
        for chapter in plan.get("chapters") or []:
            lines.append(
                f"  {chapter.get('unit')}: «{_text(chapter.get('title'), language)}»"
                f" ({_text(chapter.get('when'), 'en')}) → ends on:"
                f" {_text(chapter.get('ends_on'), 'en')}"
            )
        if isinstance(plan.get("rally"), dict):
            lines.append(f"  rally: «{_text(plan['rally'].get('title'), language)}»")
    cast = {m.get("id"): m.get("name") for m in content.get("cast") or [] if isinstance(m, dict)}
    places = {
        p.get("id"): _text(p.get("title"), language)
        for p in content.get("places") or []
        if isinstance(p, dict)
    }
    props = {
        p.get("id"): _text(p.get("label"), language)
        for p in content.get("props") or []
        if isinstance(p, dict)
    }
    questions = {q.get("id"): q for q in content.get("questions") or [] if isinstance(q, dict)}
    exercises = {e.get("id"): e for e in content.get("exercises") or [] if isinstance(e, dict)}
    games = {g.get("id"): g for g in content.get("minigames") or [] if isinstance(g, dict)}
    for number, chapter in enumerate(content.get("chapters") or [], start=1):
        covers = chapter.get("covers") if isinstance(chapter.get("covers"), dict) else {}
        label = "rally" if covers.get("rally") else f"lesson {covers.get('unit_number', '?')}"
        lines.append("")
        lines.append(f"== Chapter {number} «{_text(chapter.get('title'), language)}» ({label}) ==")
        for scene in chapter.get("scenes") or []:
            on_stage = ", ".join(str(cast.get(c, c)) for c in scene.get("cast") or [])
            shown = ", ".join(props.get(p, p) for p in scene.get("props") or [])
            lines.append(
                f"[{places.get(scene.get('place'), scene.get('place'))}] ({on_stage})"
                + (f" props: {shown}" if shown else "")
            )
            for step in scene.get("steps") or []:
                lines.append(
                    "  " + _step_line(step, language, cast, props, questions, exercises, games)
                )
    return lines


def _step_line(step, language, cast, props, questions, exercises, games) -> str:
    kind = step.get("type")
    pointed = [props.get(p, p) for p in step.get("props") or []]
    tail = f"   ⟨{', '.join(pointed)}⟩" if pointed else ""
    marks = "".join(f" ({mark})" for mark in ("refrain", "retold") if step.get(mark))
    if kind == "narrate":
        return f"narrator: {_text(step.get(language), language)}{marks}{tail}"
    if kind == "say":
        who = cast.get(step.get("who"), step.get("who"))
        return f"{who} ({step.get('mood', 'talk')}): {_text(step.get(language), language)}{marks}{tail}"
    if kind == "concept":
        rows = " | ".join(str(r) for r in step.get(language) or [])
        return f"[card «{_text(step.get('title'), language)}»: {rows}]{tail}"
    if kind == "ask":
        question = questions.get(step.get("ref")) or {}
        return f"[question {step.get('ref')}: {_text(question.get('prompt'), language)}]"
    if kind == "show" and step.get("visual") == "prop":
        return f"[look closely: {props.get((step.get('params') or {}).get('prop'))}]"
    if kind == "show":
        return f"[show {step.get('visual')}: {_text(step.get('caption'), language)}]"
    if kind == "game":
        return f"[game: {_text((games.get(step.get('ref')) or {}).get('title'), language)}]"
    if kind == "photo":
        exercise = exercises.get(step.get("ref")) or {}
        return f"[paper task {step.get('ref')}: {_text(exercise.get('prompt'), language)}]"
    return f"[{kind}]"


async def print_story(
    session, module_id: uuid.UUID, language: str, record, dump: str | None
) -> None:
    """The plan, the transcript and each chapter's story quality; and the JSON dump."""
    plan_row = await find_plan(session, module_id, language)
    plan = (plan_row.content or {}).get("plan") if plan_row is not None else None
    content = record.content if record is not None else None
    for line in story_transcript(content, plan):
        print(f"    {line}")
    units = await load_story_units(session, module_id)
    rows = await chapter_rows(session, [u.module_unit_id for u in units if u.role == "lesson"])
    chapters = {}
    for unit in units:
        row = rows.get((unit.module_unit_id, language))
        if row is None:
            continue
        checks = (row.content or {}).get("checks") or {}
        quality = checks.get("story_quality")
        print(f"    story_quality {unit.unit_number}: {json.dumps(quality, sort_keys=True)}")
        chapters[unit.unit_number] = {
            "content": row.content,
            "source_rows": {k: v for k, v in (row.source_rows or {}).items() if k != "pack"},
            "pack": (row.source_rows or {}).get("pack"),
            "validation": row.validation_report,
        }
    manifest = (
        record.source_rows if record is not None and isinstance(record.source_rows, dict) else {}
    )
    rally = manifest.get("rally") if isinstance(manifest.get("rally"), dict) else None
    if rally and isinstance(rally.get("doc"), dict):
        quality = (rally["doc"].get("checks") or {}).get("story_quality")
        print(f"    story_quality rally: {json.dumps(quality, sort_keys=True)}")
    if dump:
        folder = Path(dump)
        folder.mkdir(parents=True, exist_ok=True)
        out = folder / f"module-{module_id}-{language}.json"
        out.write_text(
            json.dumps(
                {
                    "module_id": str(module_id),
                    "language": language,
                    "plan": plan_row.content if plan_row is not None else None,
                    "plan_model": plan_row.model if plan_row is not None else None,
                    "chapters": chapters,
                    "rally": rally,
                    "module_story": content,
                },
                ensure_ascii=False,
                indent=1,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"    dumped to {out}")


@dataclass(frozen=True)
class GenerationSpec:
    """One course whose module ``module_index`` gets a story in each of ``languages``."""

    course: Course
    module_index: int
    languages: tuple[str, ...]
    #: Set when a request names the module itself; ``module_index`` is unused then.
    module_id: uuid.UUID | None = None


async def run_generation(
    session_factory,
    specs: list[GenerationSpec],
    *,
    force: bool,
    level: int,
    country: str,
    timeout_s: int,
    dump: str | None = None,
) -> int:
    """Dispatch every module story, wait for all of them, report each; 0 if
    all of them completed and are valid and published."""
    from app.api.v1.story_courses import dispatch_module_story_generation

    jobs: list[tuple[ModuleTarget, str, str]] = []
    failed = False
    async with session_factory() as session:
        for spec in specs:
            course = spec.course
            target, why = await module_target(session, course, spec.module_index, spec.module_id)
            if target is None:
                print(
                    f"Course {course.slug}: no module {spec.module_id or spec.module_index}: {why}"
                )
                failed = True
                continue
            if not target.lessons:
                print(
                    f"Course {course.slug}: module {target.module.module_number} has no "
                    "lesson unit, so it has no story"
                )
                failed = True
                continue
            for language in spec.languages:
                task_id = await dispatch_module_story_generation(
                    module_id=target.module.id,
                    language=language,
                    country=country,
                    level=level,
                    force_regenerate=force,
                )
                print(
                    f"Dispatched {course.slug} module {target.module.module_number} "
                    f"[{language}] task={task_id}"
                )
                jobs.append((target, language, task_id))

    outcomes = await asyncio.gather(*(wait_for_task(t, timeout_s) for _, _, t in jobs))

    async with session_factory() as session:
        for (target, language, task_id), (state, result) in zip(jobs, outcomes, strict=True):
            print("=" * 72)
            print(
                f"{target.course.title_fr} — module {target.module.module_number} "
                f"«{target.module.title_fr}» [{language}]: {len(target.units)} unit(s), "
                f"{len(target.lessons)} lesson(s)"
            )
            completed = (
                state == "SUCCESS"
                and isinstance(result, dict)
                and result.get("status") == "complete"
            )
            print(f"  task {task_id}: {state} {'' if completed else result}".rstrip())
            if isinstance(result, dict) and result.get("failed_units"):
                print(f"  failed units={result['failed_units']}")
            record = await find_module_story(session, target.module.id, language)
            summary = module_story_summary(record)
            print_module_summary("  ", summary)
            await print_story(session, target.module.id, language, record, dump)
            ok = completed and summary.get("is_valid") and summary.get("status") == "published"
            failed = failed or not ok
    return 1 if failed or not jobs else 0


async def cmd_generate(
    session_factory,
    course_refs: list[str],
    languages: list[str],
    *,
    force: bool,
    module_index: int,
    level: int,
    country: str,
    timeout_s: int,
    dump: str | None = None,
) -> int:
    specs: list[GenerationSpec] = []
    missing = False
    async with session_factory() as session:
        for ref in course_refs:
            course = await resolve_course(session, ref)
            if course is None:
                print(f"Course {ref!r}: not found")
                missing = True
                continue
            specs.append(GenerationSpec(course, module_index, tuple(languages)))
    code = await run_generation(
        session_factory,
        specs,
        force=force,
        level=level,
        country=country,
        timeout_s=timeout_s,
        dump=dump,
    )
    return 1 if missing else code


def load_requests(path: str) -> list[dict[str, Any]]:
    """The ``requests`` list of a story request file, each entry checked.

    Each entry asks for one module's story. It names courses by ``query`` (a
    title or slug fragment) and may set ``kids_only`` (default false),
    ``include_drafts`` (default false), ``max_courses`` (default 1: a query
    matching more courses is refused, so a vague query never pays for stories
    nobody asked for), ``module_index`` (default 1: the course's first module
    by number) and ``languages`` (default fr and en). Or it names one module
    by ``module_id`` (a UUID), whatever its course's status. A
    ``lesson_index`` (from the per-lesson stories) is ignored with a warning.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    requests = data.get("requests") if isinstance(data, dict) else None
    if not isinstance(requests, list) or not requests:
        raise ValueError(f"{path}: no 'requests' list")
    checked = []
    for index, entry in enumerate(requests):
        if not isinstance(entry, dict) or not (
            str(entry.get("query") or "").strip() or entry.get("module_id")
        ):
            raise ValueError(f"{path}: requests[{index}] needs a 'query' or a 'module_id'")
        module_id = None
        if entry.get("module_id"):
            try:
                module_id = uuid.UUID(str(entry["module_id"]))
            except ValueError as exc:
                raise ValueError(f"{path}: requests[{index}] has a bad module_id") from exc
        languages = entry.get("languages") or list(LANGUAGES)
        if not set(languages) <= set(LANGUAGES):
            raise ValueError(f"{path}: requests[{index}] has unknown languages {languages}")
        module_index = int(entry.get("module_index", 1))
        if module_index < 1:
            raise ValueError(f"{path}: requests[{index}] has module_index {module_index} (< 1)")
        if "lesson_index" in entry:
            warn(f"{path}: requests[{index}].{LESSON_INDEX_IGNORED}")
        checked.append(
            {
                "query": str(entry.get("query") or "").strip(),
                "module_id": module_id,
                "kids_only": bool(entry.get("kids_only", False)),
                "include_drafts": bool(entry.get("include_drafts", False)),
                "max_courses": int(entry.get("max_courses", 1)),
                "module_index": module_index,
                "languages": tuple(languages),
            }
        )
    return checked


async def cmd_requests(
    session_factory,
    path: str,
    *,
    force: bool,
    level: int,
    country: str,
    timeout_s: int,
    dump: str | None = None,
) -> int:
    """Generate the module stories a request file asks for (see :func:`load_requests`).

    The same file runs after every deploy, on staging and on production, where
    different courses exist: a request that matches nothing there is skipped
    with a note. A vague query (too many matches) and any story that does not
    end valid and published fail the run.
    """
    requests = load_requests(path)
    specs: list[GenerationSpec] = []
    refused = False
    async with session_factory() as session:
        for request in requests:
            if request["module_id"] is not None:
                module = (
                    await session.execute(
                        select(Module)
                        .options(selectinload(Module.course))
                        .where(Module.id == request["module_id"])
                    )
                ).scalar_one_or_none()
                if module is None or module.course is None:
                    print(f"module {request['module_id']}: not on this server; skipped")
                    continue
                print(f"module {module.id}: {module.course.slug} ({module.course.title_fr})")
                specs.append(
                    GenerationSpec(
                        module.course,
                        request["module_index"],
                        request["languages"],
                        module_id=module.id,
                    )
                )
                continue
            matches = await find_courses(session, [request["query"]])
            courses = [
                c
                for c in matches
                if (request["include_drafts"] or c.status == "published")
                and (not request["kids_only"] or detect_audience(c).is_kids)
            ]
            label = f"query {request['query']!r}{' (kids)' if request['kids_only'] else ''}"
            if not courses:
                print(f"{label}: no matching course on this server; skipped.")
                for course in matches:
                    print(
                        f"  near match - {course.slug}: {course.title_fr} "
                        f"status={course.status} kids={detect_audience(course).is_kids}"
                    )
                continue
            if len(courses) > request["max_courses"]:
                print(
                    f"{label}: {len(courses)} courses match, more than max_courses="
                    f"{request['max_courses']}; nothing generated for it. Candidates:"
                )
                for course in courses:
                    print(f"  - {course.slug}: {course.title_fr} / {course.title_en}")
                refused = True
                continue
            for course in courses:
                print(f"{label}: {course.slug} ({course.title_fr})")
                specs.append(GenerationSpec(course, request["module_index"], request["languages"]))
    if not specs:
        print("Nothing to generate on this server.")
        return 1 if refused else 0
    code = await run_generation(
        session_factory,
        specs,
        force=force,
        level=level,
        country=country,
        timeout_s=timeout_s,
        dump=dump,
    )
    return 1 if refused else code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--module-index", type=int, default=1, help="1 = the first module")
        p.add_argument(
            "--lesson-index",
            type=int,
            default=None,
            help="ignored: a story covers a whole module (kept for old callers)",
        )

    listing = sub.add_parser(
        "list", help="show matching courses, their module's units, chapters and story"
    )
    listing.add_argument("--query", action="append", required=True)
    common(listing)

    generate = sub.add_parser("generate", help="generate (or reuse) the module stories")
    generate.add_argument("--course", action="append", required=True, help="slug or UUID")
    generate.add_argument("--language", action="append", choices=LANGUAGES)
    generate.add_argument(
        "--force", action="store_true", help="remake every chapter even if fresh (paid)"
    )
    generate.add_argument("--level", type=int, default=1, help="preferred source lesson level")
    generate.add_argument("--country", default="CI", help="preferred source lesson country")
    generate.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="seconds to wait")
    generate.add_argument("--dump", default=None, help="write the plan and chapters as JSON here")
    common(generate)

    requests = sub.add_parser("requests", help="generate what a request file asks for")
    requests.add_argument("file", help="JSON request file (see load_requests)")
    requests.add_argument(
        "--force", action="store_true", help="remake every chapter even if fresh (paid)"
    )
    requests.add_argument("--level", type=int, default=1, help="preferred source lesson level")
    requests.add_argument("--country", default="CI", help="preferred source lesson country")
    requests.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S, help="seconds to wait")
    requests.add_argument("--dump", default=None, help="write the plan and chapters as JSON here")
    args = parser.parse_args(argv)
    if getattr(args, "module_index", 1) < 1:
        parser.error("--module-index must be 1 or more")
    if getattr(args, "lesson_index", None) is not None:
        warn(f"--{LESSON_INDEX_IGNORED.replace('_', '-')}")
    return args


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    if args.command == "list":
        return await cmd_list(session_factory, args.query, args.module_index)
    if args.command == "requests":
        return await cmd_requests(
            session_factory,
            args.file,
            force=args.force,
            level=args.level,
            country=args.country,
            timeout_s=args.timeout,
            dump=args.dump,
        )
    return await cmd_generate(
        session_factory,
        args.course,
        args.language or list(LANGUAGES),
        force=args.force,
        module_index=args.module_index,
        level=args.level,
        country=args.country,
        timeout_s=args.timeout,
        dump=args.dump,
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
