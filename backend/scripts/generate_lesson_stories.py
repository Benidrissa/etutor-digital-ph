#!/usr/bin/env python3
"""List or generate the story mode of a course's first lesson, from the server.

Story mode is normally generated the first time a learner opens a lesson's
Story tab. This script lets an operator do it ahead of time for chosen
courses, through the very same path: it dispatches ``generate_story_task``
with the API's dedup key (so it joins a generation a learner already
started rather than paying for a second one), waits for the worker, then
prints what was stored.

Usage (inside the backend container)::

    # Which courses match, which lesson is "lesson 1", what is cached
    python scripts/generate_lesson_stories.py list --query biolog --query math

    # Generate lesson 1 of module 1 of each course, in French and English
    python scripts/generate_lesson_stories.py generate \
        --course <slug-or-uuid> --course <slug-or-uuid> --language fr --language en

    # Generate what a request file asks for (run after every deploy)
    python scripts/generate_lesson_stories.py requests scripts/story_requests.json

``generate`` and ``requests`` exit non-zero unless every story ended up valid
and published. Re-running them is cheap: a story that is already cached and
fresh is returned as it is, with no model call.
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
from app.domain.models.module_unit import ModuleUnit  # noqa: E402
from app.domain.models.story_course import StoryCourseRecord  # noqa: E402
from app.domain.services.story_from_lesson_service import (  # noqa: E402
    _unit_order,
    covering_quiz_unit,
    find_unit_story,
    is_lesson_unit,
)

LANGUAGES = ("fr", "en")
_FINISHED_STATES = frozenset({"SUCCESS", "FAILURE", "REVOKED"})


@dataclass(frozen=True)
class LessonTarget:
    """One course's chosen lesson: the unit whose story is generated."""

    course: Course
    module: Module
    unit: ModuleUnit
    quiz_unit: ModuleUnit | None


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


async def lesson_target(
    session,
    course: Course,
    module_index: int,
    lesson_index: int,
    module_id: uuid.UUID | None = None,
) -> tuple[LessonTarget | None, str]:
    """The ``lesson_index``-th lesson of the ``module_index``-th module (or of
    the module ``module_id``), in teaching order: modules by number, units by
    order then unit number."""
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
    units = sorted(
        (await session.execute(select(ModuleUnit).where(ModuleUnit.module_id == module.id)))
        .scalars()
        .all(),
        key=_unit_order,
    )
    lessons = [u for u in units if is_lesson_unit(u.unit_type)]
    if len(lessons) < lesson_index:
        return None, f"module {module.module_number} has {len(lessons)} lesson unit(s)"
    unit = lessons[lesson_index - 1]
    return LessonTarget(course, module, unit, covering_quiz_unit(units, unit.id)), ""


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


# -- reporting ---------------------------------------------------------------


def story_summary(record: StoryCourseRecord | None) -> dict[str, Any]:
    """What an operator needs to judge one stored story."""
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


def story_excerpt(content: dict[str, Any] | None, limit: int = 8) -> list[str]:
    """A few lines to judge a story by from a log: its title, chapter titles
    and question prompts, in the language it teaches in. The learner's name is
    still the ``{child}`` placeholder in a stored story."""
    if not isinstance(content, dict):
        return []
    language = (content.get("languages") or {}).get("target") or "fr"

    def text(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get(language) or next(iter(value.values()), "")
        return " ".join(str(value or "").split())[:160]

    lines = [f"title: {text(content.get('title'))}"]
    for chapter in (content.get("chapters") or [])[:limit]:
        if isinstance(chapter, dict):
            lines.append(f"chapter: {text(chapter.get('title'))}")
    for question in (content.get("questions") or [])[:limit]:
        if isinstance(question, dict):
            lines.append(f"{question.get('id', '?')}: {text(question.get('prompt'))}")
    return lines


def print_summary(prefix: str, summary: dict[str, Any]) -> None:
    if not summary.get("stored"):
        print(f"{prefix}story: none")
        return
    print(
        f"{prefix}story: {summary['slug']} status={summary['status']} "
        f"valid={summary['is_valid']} max_points={summary['max_points']} "
        f"questions={summary['questions']} exercises={summary['exercises']} "
        f"from_quiz={summary['questions_from_quiz']}"
    )
    print(f"{prefix}  errors={summary['errors'] or 'none'}")
    print(f"{prefix}  warnings={summary['warnings'] or 'none'}")


# -- commands ----------------------------------------------------------------


async def cmd_list(session_factory, queries: list[str], module_index: int, lesson_index: int):
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
            target, why = await lesson_target(session, course, module_index, lesson_index)
            if target is None:
                print(f"  no lesson {lesson_index} in module {module_index}: {why}")
                continue
            unit_ids = [target.unit.id] + ([target.quiz_unit.id] if target.quiz_unit else [])
            counts = await cached_rows(session, unit_ids)
            print(
                f"  module {target.module.module_number}: {target.module.title_fr} "
                f"(id={target.module.id})"
            )
            print(
                f"  lesson unit {target.unit.unit_number}: {target.unit.title_fr} "
                f"(type={target.unit.unit_type}, id={target.unit.id})"
            )
            if target.quiz_unit is not None:
                print(f"  covering quiz unit: {target.quiz_unit.unit_number}")
            else:
                print("  covering quiz unit: none")
            for language in LANGUAGES:
                lessons = counts.get((target.unit.id, "lesson", language), 0)
                quizzes = sum(counts.get((uid, "quiz", language), 0) for uid in unit_ids)
                print(f"  [{language}] cached lessons={lessons} quizzes={quizzes}")
                record = await find_unit_story(session, target.unit.id, language)
                print_summary(f"  [{language}] ", story_summary(record))
    return 0


async def wait_for_task(task_id: str, timeout_s: int, poll_s: float = 5.0) -> tuple[str, Any]:
    """Poll a Celery task until it finishes or ``timeout_s`` passes."""
    from celery.result import AsyncResult

    waited = 0.0
    while True:
        result = AsyncResult(task_id)
        state = result.state
        if state in _FINISHED_STATES:
            return state, result.result
        if waited >= timeout_s:
            return f"TIMEOUT({state})", None
        await asyncio.sleep(poll_s)
        waited += poll_s


@dataclass(frozen=True)
class GenerationSpec:
    """One course whose ``lesson_index``-th lesson of module ``module_index``
    gets a story in each of ``languages``."""

    course: Course
    module_index: int
    lesson_index: int
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
) -> int:
    """Dispatch every story, wait for all of them, report each; 0 if all are
    valid and published."""
    from app.api.v1.story_courses import _dispatch_story_generation

    jobs: list[tuple[LessonTarget, str, str]] = []
    failed = False
    async with session_factory() as session:
        for spec in specs:
            course = spec.course
            target, why = await lesson_target(
                session, course, spec.module_index, spec.lesson_index, spec.module_id
            )
            if target is None:
                print(
                    f"Course {course.slug}: no lesson {spec.lesson_index} in module "
                    f"{spec.module_id or spec.module_index}: {why}"
                )
                failed = True
                continue
            for language in spec.languages:
                task_id = await _dispatch_story_generation(
                    module_id=target.module.id,
                    unit_id=target.unit.unit_number,
                    module_unit_id=target.unit.id,
                    language=language,
                    country=country,
                    level=level,
                    force_regenerate=force,
                )
                print(
                    f"Dispatched {course.slug} unit {target.unit.unit_number} [{language}] "
                    f"task={task_id}"
                )
                jobs.append((target, language, task_id))

    outcomes = await asyncio.gather(*(wait_for_task(t, timeout_s) for _, _, t in jobs))

    async with session_factory() as session:
        for (target, language, task_id), (state, result) in zip(jobs, outcomes, strict=True):
            print("=" * 72)
            print(
                f"{target.course.title_fr} — module {target.module.module_number}, "
                f"unit {target.unit.unit_number} «{target.unit.title_fr}» [{language}]"
            )
            print(f"  task {task_id}: {state} {result if state != 'SUCCESS' else ''}".rstrip())
            record = await find_unit_story(session, target.unit.id, language)
            summary = story_summary(record)
            print_summary("  ", summary)
            for line in story_excerpt(record.content if record is not None else None):
                print(f"    {line}")
            ok = (
                state == "SUCCESS"
                and summary.get("is_valid")
                and summary.get("status") == "published"
            )
            failed = failed or not ok
    return 1 if failed or not jobs else 0


async def cmd_generate(
    session_factory,
    course_refs: list[str],
    languages: list[str],
    *,
    force: bool,
    module_index: int,
    lesson_index: int,
    level: int,
    country: str,
    timeout_s: int,
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
            specs.append(GenerationSpec(course, module_index, lesson_index, tuple(languages)))
    code = await run_generation(
        session_factory, specs, force=force, level=level, country=country, timeout_s=timeout_s
    )
    return 1 if missing else code


def load_requests(path: str) -> list[dict[str, Any]]:
    """The ``requests`` list of a story request file, each entry checked.

    An entry names courses by ``query`` (a title or slug fragment) and may set
    ``kids_only`` (default false), ``include_drafts`` (default false),
    ``max_courses`` (default 1: a query matching more courses is refused, so a
    vague query never pays for stories nobody asked for), ``module_index`` and
    ``lesson_index`` (default 1) and ``languages`` (default fr and en). Or it
    names one module by ``module_id`` (a UUID), whatever its course's status.
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
        checked.append(
            {
                "query": str(entry.get("query") or "").strip(),
                "module_id": module_id,
                "kids_only": bool(entry.get("kids_only", False)),
                "include_drafts": bool(entry.get("include_drafts", False)),
                "max_courses": int(entry.get("max_courses", 1)),
                "module_index": int(entry.get("module_index", 1)),
                "lesson_index": int(entry.get("lesson_index", 1)),
                "languages": tuple(languages),
            }
        )
    return checked


async def cmd_requests(
    session_factory, path: str, *, force: bool, level: int, country: str, timeout_s: int
) -> int:
    """Generate the stories a request file asks for (see :func:`load_requests`).

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
                        request["lesson_index"],
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
                specs.append(
                    GenerationSpec(
                        course,
                        request["module_index"],
                        request["lesson_index"],
                        request["languages"],
                    )
                )
    if not specs:
        print("Nothing to generate on this server.")
        return 1 if refused else 0
    code = await run_generation(
        session_factory, specs, force=force, level=level, country=country, timeout_s=timeout_s
    )
    return 1 if refused else code


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--module-index", type=int, default=1, help="1 = the first module")
        p.add_argument("--lesson-index", type=int, default=1, help="1 = its first lesson")

    listing = sub.add_parser("list", help="show matching courses and their lesson 1")
    listing.add_argument("--query", action="append", required=True)
    common(listing)

    generate = sub.add_parser("generate", help="generate (or reuse) the stories")
    generate.add_argument("--course", action="append", required=True, help="slug or UUID")
    generate.add_argument("--language", action="append", choices=LANGUAGES)
    generate.add_argument("--force", action="store_true", help="regenerate even if fresh")
    generate.add_argument("--level", type=int, default=1, help="preferred source lesson level")
    generate.add_argument("--country", default="CI", help="preferred source lesson country")
    generate.add_argument("--timeout", type=int, default=1200, help="seconds to wait")
    common(generate)

    requests = sub.add_parser("requests", help="generate what a request file asks for")
    requests.add_argument("file", help="JSON request file (see load_requests)")
    requests.add_argument("--force", action="store_true", help="regenerate even if fresh")
    requests.add_argument("--level", type=int, default=1, help="preferred source lesson level")
    requests.add_argument("--country", default="CI", help="preferred source lesson country")
    requests.add_argument("--timeout", type=int, default=1200, help="seconds to wait")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    if args.command == "list":
        return await cmd_list(session_factory, args.query, args.module_index, args.lesson_index)
    if args.command == "requests":
        return await cmd_requests(
            session_factory,
            args.file,
            force=args.force,
            level=args.level,
            country=args.country,
            timeout_s=args.timeout,
        )
    return await cmd_generate(
        session_factory,
        args.course,
        args.language or list(LANGUAGES),
        force=args.force,
        module_index=args.module_index,
        lesson_index=args.lesson_index,
        level=args.level,
        country=args.country,
        timeout_s=args.timeout,
    )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
