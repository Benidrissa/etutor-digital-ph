#!/usr/bin/env python3
"""What does each stored module story show, and how does it talk? (#2708)

One row per stored module story: its close-ups with no picture (no course
figure, nothing from the prop library), the longest run of ``say`` lines, the
mentor's share of the lines, the most words before a chapter's first card,
the longest card, refrains, questions or paper tasks naming a prop not shown
before them, French in ``en`` fields, "look" lines with nothing shown, and
educational props with no picture. The numbers come from
:mod:`app.domain.services.story_metrics`, the validator's own.

Read-only: SELECTs only (the stories and the cached prop matches), no model
call, no write, no commit. The database is the application's own
(``DATABASE_URL``, as every script here). Usage (inside the backend container)::

    python scripts/audit_story_assets.py
    python scripts/audit_story_assets.py --published-only --markdown
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.models.story_course import StoryCourseRecord  # noqa: E402
from app.domain.services import story_metrics as metrics  # noqa: E402
from app.domain.services.story_prop_library import (  # noqa: E402
    document_props,
    load_matches,
    props_media,
)

COLUMNS = (
    ("story", "story"),
    ("lang", "lang"),
    ("status", "status"),
    ("closeups", "show"),
    ("without_art", "show no art"),
    ("say_run_max", "say run"),
    ("mentor_share", "mentor"),
    ("words_before_first_card", "words>card"),
    ("card_words_max", "card max"),
    ("refrain_count", "refrains"),
    ("unseen_stimulus", "unseen"),
    ("french_in_en", "FR in en"),
    ("dangling_deixis", "deixis"),
    ("educational_without_art", "edu no art"),
)


def audit_row(
    content: Mapping[str, Any], art_props: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The numbers of one story document (pure). ``art_props``: the library's ``art.props``."""
    doc = dict(content)
    if art_props:
        art = dict(doc.get("art") or {})
        art["props"] = {**(art.get("props") or {}), **art_props}
        doc["art"] = art
    numbers = metrics.story_metrics(doc)
    findings = Counter(f.code for f in metrics.all_findings(doc))
    return {
        "closeups": numbers["closeups"],
        "without_art": numbers["closeups"] - numbers["closeups_with_art"],
        "say_run_max": numbers["say_run_max"],
        "mentor_share": numbers["mentor_share"],
        "words_before_first_card": numbers["words_before_first_card"],
        "card_words_max": numbers["card_words_max"],
        "refrain_count": numbers["refrain_count"],
        "unseen_stimulus": findings["unseen_stimulus"],
        "french_in_en": findings["lang_integrity"],
        "dangling_deixis": findings["dangling_deixis"],
        "educational_without_art": findings["educational_prop_without_art"],
    }


def format_table(rows: Iterable[Mapping[str, Any]], *, markdown: bool = False) -> str:
    """The rows as an aligned text table, or a Markdown one for a GitHub comment."""
    cells = [[str(row.get(key, "")) for key, _title in COLUMNS] for row in rows]
    titles = [title for _key, title in COLUMNS]
    if markdown:
        lines = ["| " + " | ".join(titles) + " |", "|" + "|".join("---" for _ in titles) + "|"]
        lines += ["| " + " | ".join(line) + " |" for line in cells]
        return "\n".join(lines)
    widths = [max(len(t), *(len(line[i]) for line in cells)) for i, t in enumerate(titles)]
    out = ["  ".join(t.ljust(w) for t, w in zip(titles, widths, strict=True))]
    out += ["  ".join(c.ljust(w) for c, w in zip(line, widths, strict=True)) for line in cells]
    return "\n".join(out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--published-only", action="store_true", help="only published stories")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table")
    return parser.parse_args(argv)


async def collect(session, *, published_only: bool = False) -> list[dict[str, Any]]:
    """One row per module story (SELECTs only)."""
    statement = (
        select(
            StoryCourseRecord.slug,
            StoryCourseRecord.language,
            StoryCourseRecord.status,
            StoryCourseRecord.content,
        )
        .where(
            StoryCourseRecord.module_id.is_not(None),
            StoryCourseRecord.module_unit_id.is_(None),
        )
        .order_by(StoryCourseRecord.slug)
    )
    if published_only:
        statement = statement.where(StoryCourseRecord.status == "published")
    rows: list[dict[str, Any]] = []
    for slug, language, status, content in (await session.execute(statement)).all():
        content = content or {}
        doc_props = document_props(content)
        resolved = await load_matches(session, [p.key for p in doc_props]) if doc_props else {}
        art = props_media(doc_props, resolved).props
        rows.append(
            {
                "story": slug,
                "lang": language or "",
                "status": str(status),
                **audit_row(content, art),
            }
        )
    return rows


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    async with session_factory() as session:
        rows = await collect(session, published_only=args.published_only)
    if not rows:
        print("No module story found.", file=sys.stderr)
        return 1
    print(format_table(rows, markdown=args.markdown))
    print(f"\n{len(rows)} stories")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
