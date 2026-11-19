#!/usr/bin/env python3
"""SELECT-only export of stored story chapters, for the director-script paper test (#2737).

Reads, writes nothing: the transaction is set READ ONLY and rolled back, and no
statement other than SELECT is issued. Each chapter becomes one JSON file, so
the paper-test harness (``story_script_paper_test.py``) runs from files and
needs no database.

Usage (inside the backend container, or any place that can reach the database
with a read-only role)::

    # which chapters exist, and which look like maths
    python scripts/story_script_export.py list --module <module-uuid> --language fr

    # export chosen chapters (unit numbers of that module)
    python scripts/story_script_export.py export --module <module-uuid> --language fr \
        --unit 1.1 --unit 1.3 --out /tmp/paper-test

A chapter file holds: the titles, the plan entry of the chapter and the plan's
global part, the stored practice pack, the lesson's fact sheet (ideas, key
facts, figures: what ``build_fact_sheet`` gives), and the stored chapter
document itself (for the storyboard of the existing chapter). Legacy plans are
only read, never changed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

_MATHS = re.compile(r"math|arithm|calcul|algèbre|algebra|géométr|geometr|nombre")


def looks_like_maths(course_title: dict[str, str], module_title: dict[str, str]) -> bool:
    """The filter of ``story_from_lesson._is_maths`` (same pattern), on plain dicts."""
    title = " ".join([*course_title.values(), *module_title.values()]).lower()
    return bool(_MATHS.search(title))


def build_bundle(
    *,
    course_title: dict[str, str],
    module_title: dict[str, str],
    module_id: str,
    language: str,
    unit: str,
    plan: dict[str, Any] | None,
    pack: dict[str, Any] | None,
    lesson: dict[str, Any] | None,
    stored: dict[str, Any] | None,
) -> dict[str, Any]:
    """One chapter's file. Pure: everything it needs is passed in."""
    from app.ai.prompts.story_from_lesson import build_fact_sheet

    plan = plan or {}
    entries = [c for c in plan.get("chapters") or [] if isinstance(c, dict)]
    entry = next((c for c in entries if str(c.get("unit")) == unit), {})
    index = next((i for i, c in enumerate(entries, start=1) if str(c.get("unit")) == unit), 1)
    sheet = build_fact_sheet(lesson)
    return {
        "id": f"{module_id[:8]}-{unit}-{language}",
        "module_id": module_id,
        "unit": unit,
        "language": language,
        "course_title": course_title,
        "module_title": module_title,
        "is_maths": looks_like_maths(course_title, module_title),
        "chapter_index": index,
        # the rally counts as a chapter (#2749)
        "chapter_count": len(entries) + (1 if isinstance(plan.get("rally"), dict) else 0),
        "plan_global": {k: v for k, v in plan.items() if k not in ("chapters", "rally")},
        "plan_entry": entry,
        "pack": pack or {},
        "fact_sheet": {
            "ideas": list(sheet.ideas),
            "key_facts": list(sheet.key_facts),
            "figures": [list(f) for f in sheet.figures],
        },
        "stored": stored or {},
    }


def pick_six(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Three maths and three other chapters, one per module where possible (a first filter)."""
    maths = [b for b in bundles if b["is_maths"]]
    other = [b for b in bundles if not b["is_maths"]]

    def spread(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        first = [b for b in items if not (b["module_id"] in seen or seen.add(b["module_id"]))]
        rest = [b for b in items if b not in first]
        return (first + rest)[:3]

    return spread(maths) + spread(other)


async def _read_only(session) -> None:
    from sqlalchemy import text

    await session.execute(text("SET TRANSACTION READ ONLY"))


async def collect(
    session, module_id: uuid.UUID, language: str, units: list[str]
) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from app.domain.models.content import GeneratedContent
    from app.domain.models.course import Course
    from app.domain.models.module import Module
    from app.domain.models.story_course import StoryCourseRecord
    from app.domain.services.story_module_service import load_story_units
    from app.domain.services.story_plan import find_plan

    module = await session.get(Module, module_id)
    if module is None:
        raise LookupError(f"no module {module_id}")
    course = await session.get(Course, module.course_id)
    plan_row = await find_plan(session, module_id, language)
    plan = (plan_row.content or {}).get("plan") if plan_row is not None else None
    story_units = [u for u in await load_story_units(session, module_id) if u.role == "lesson"]
    rows = (
        (
            await session.execute(
                select(StoryCourseRecord).where(
                    StoryCourseRecord.module_unit_id.in_([u.module_unit_id for u in story_units]),
                    StoryCourseRecord.language == language,
                )
            )
        )
        .scalars()
        .all()
    )
    by_unit = {r.module_unit_id: r for r in rows}
    bundles = []
    for unit in story_units:
        if units and unit.unit_number not in units:
            continue
        row = by_unit.get(unit.module_unit_id)
        if row is None:
            continue
        lesson = None
        if row.source_lesson_content_id is not None:
            found = await session.get(GeneratedContent, row.source_lesson_content_id)
            lesson = found.content if found is not None else None
        sources = row.source_rows if isinstance(row.source_rows, dict) else {}
        bundles.append(
            build_bundle(
                course_title={"en": course.title_en, "fr": course.title_fr},
                module_title={"en": module.title_en, "fr": module.title_fr},
                module_id=str(module_id),
                language=language,
                unit=unit.unit_number,
                plan=plan,
                pack=sources.get("pack"),
                lesson=lesson,
                stored=row.content,
            )
        )
    return bundles


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "export"):
        p = sub.add_parser(name)
        p.add_argument("--module", action="append", required=True, help="module UUID (repeatable)")
        p.add_argument("--language", default="fr", choices=("fr", "en"))
        p.add_argument("--unit", action="append", default=[], help="unit number (repeatable)")
        if name == "export":
            p.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    bundles: list[dict[str, Any]] = []
    async with session_factory() as session:
        try:
            await _read_only(session)
            for ref in args.module:
                bundles += await collect(session, uuid.UUID(ref), args.language, args.unit)
        finally:
            await session.rollback()  # nothing was written; end the transaction
    if args.command == "list":
        for b in bundles:
            print(
                f"{b['id']}  maths={b['is_maths']}  {b['course_title'].get('en')} / {b['module_title'].get('en')}"
            )
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for b in bundles:
        (out / f"chapter-{b['id']}.json").write_text(
            json.dumps(b, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
        )
    print(f"{len(bundles)} chapter file(s) in {out}")
    return 0 if bundles else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
