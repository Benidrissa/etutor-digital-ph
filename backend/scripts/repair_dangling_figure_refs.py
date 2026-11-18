#!/usr/bin/env python3
"""Repoint lesson figure refs whose ``source_images`` row was deleted (#2707).

Re-indexing a course re-creates its ``source_images`` rows under new ids, so
lessons generated earlier name rows that no longer exist: the figure answers
404 and the story generator drops it. This script finds, for every dangling
ref, the row that replaced it in the same course (by caption and figure
number, or by figure number when it names a single picture) and rewrites the
lesson. See ``app/domain/services/figure_ref_repair.py``.

**Dry run by default**: nothing is written without ``--apply``. Running it
twice is safe: a repointed ref is no longer dangling.

A repointed lesson keeps its stories as they are (the chapter's pin is moved
to the lesson's new digest), so no story is written again by the model. Pass
``--let-stories-regenerate`` to leave the pins alone instead: each story
chapter of a repointed lesson is then stale and is regenerated, with model
calls, on its next visit.

Usage (inside the backend container)::

    python scripts/repair_dangling_figure_refs.py                    # dry run, all courses
    python scripts/repair_dangling_figure_refs.py --course <uuid>    # dry run, one course
    python scripts/repair_dangling_figure_refs.py --apply
    python scripts/repair_dangling_figure_refs.py --json /tmp/figure-refs.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.models.course import Course  # noqa: E402
from app.domain.services.figure_ref_repair import (  # noqa: E402
    RepairReport,
    repoint_course_figure_refs,
)


def summarise(reports: list[RepairReport]) -> dict[str, Any]:
    """Totals over the courses, plus the count of each reason a ref was left alone."""
    reasons: dict[str, int] = {}
    methods: dict[str, int] = {}
    for report in reports:
        for row in report.rows:
            for _old, reason in row.unmatched:
                reasons[reason] = reasons.get(reason, 0) + 1
            for repoint in row.repoints:
                methods[repoint.method] = methods.get(repoint.method, 0) + 1
    return {
        "courses_with_dangling_refs": sum(1 for r in reports if r.rows),
        "rows": sum(len(r.rows) for r in reports),
        "repointed": sum(r.repointed for r in reports),
        "repointed_by": dict(sorted(methods.items())),
        "unmatched": sum(r.unmatched for r in reports),
        "unmatched_because": dict(sorted(reasons.items())),
        "stories_repinned": sum(r.stories_repinned for r in reports),
    }


def render(reports: list[RepairReport], *, applied: bool) -> str:
    lines = []
    for report in reports:
        if not report.rows:
            continue
        lines.append(
            f"course {report.course_id}: {len(report.rows)} row(s), "
            f"{report.repointed} repointed, {report.unmatched} unmatched"
        )
        for row in report.rows:
            for repoint in row.repoints:
                lines.append(
                    f"  {row.content_id}  {repoint.old} -> {repoint.new}  ({repoint.method})"
                )
            for old, reason in row.unmatched:
                lines.append(f"  {row.content_id}  {old} -> ?  ({reason})")
    totals = summarise(reports)
    lines.append("")
    lines.append(("APPLIED" if applied else "DRY RUN (nothing written; pass --apply)") + ":")
    for key, value in totals.items():
        lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--course", default=None, help="only this course (uuid)")
    parser.add_argument(
        "--apply", action="store_true", help="write the repoints (default: dry run)"
    )
    parser.add_argument(
        "--let-stories-regenerate",
        action="store_true",
        help="do not move story pins: story chapters of repointed lessons become stale",
    )
    parser.add_argument("--json", default=None, help="also write the full report to this file")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory

    reports: list[RepairReport] = []
    async with session_factory() as session:
        stmt = select(Course.id).where(Course.rag_collection_id.is_not(None)).order_by(Course.id)
        if args.course:
            stmt = stmt.where(Course.id == uuid.UUID(args.course))
        course_ids = list((await session.execute(stmt)).scalars())
        for course_id in course_ids:
            reports.append(
                await repoint_course_figure_refs(
                    session,
                    course_id,
                    dry_run=not args.apply,
                    keep_stories=not args.let_stories_regenerate,
                )
            )
        if args.apply:
            await session.commit()
        else:
            await session.rollback()

    print(render(reports, applied=args.apply))
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {
                    "summary": summarise(reports),
                    "courses": [r.as_dict() for r in reports if r.rows],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
