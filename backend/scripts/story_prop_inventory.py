#!/usr/bin/env python3
"""What props do the stories ask for? (Phase 0 of the 3D asset library.)

docs/story-mode-3d-assets.md plans a shared library of prop stickers rendered
from free 3D models. Before anything is built, this script measures the
demand: every prop declared by a stored story document (``content.props``)
or a module's episode plan (``content.plan.props``), ranked by how many
modules and courses use it.

A prop counts once per *scope* and language: a module (its chapter rows, its
module story and its plan all repeat the same props) or a hand-authored week.
Two rankings are printed:

* **by head noun**, the shopping list: "woven straw basket" and "wicker
  basket" are both a *basket* (the last word of the search phrase, before
  any "of"/"with", made singular; a heuristic, so Latin names group badly);
* **by search phrase**, exactly as the screenplay wrote ``prop.query``.

With ``--library`` (a JSON list of model names, see :func:`load_library`),
each head noun is also matched against the names, for a first, lexical
estimate of the library's hit rate. The real matcher will use embeddings.

Read-only: three SELECTs, no model call, no write. Usage (inside the backend
container)::

    python scripts/story_prop_inventory.py
    python scripts/story_prop_inventory.py --course <slug-or-uuid> --top 0
    python scripts/story_prop_inventory.py --published-only --json /tmp/props.json
    python scripts/story_prop_inventory.py --library scripts/story_prop_candidates.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.domain.models.course import Course  # noqa: E402
from app.domain.models.module import Module  # noqa: E402
from app.domain.models.story_course import StoryCourseRecord  # noqa: E402
from app.domain.models.story_module_plan import StoryModulePlan  # noqa: E402
from app.domain.services.story_prop_library import (  # noqa: E402
    head_noun,
    normalise_query,
    singular,
    tokens,
)

DEFAULT_TOP = 60


# -- Collecting -------------------------------------------------------------------


@dataclass
class Tally:
    """One ranked entry: a head noun or a search phrase."""

    key: str
    scopes: set[tuple[str, str]] = field(default_factory=set)
    courses: set[str] = field(default_factory=set)
    languages: set[str] = field(default_factory=set)
    kinds: Counter = field(default_factory=Counter)
    queries: Counter = field(default_factory=Counter)
    label_en: str = ""
    label_fr: str = ""
    emoji: str = ""
    match: str | None = None

    @property
    def modules(self) -> int:
        """Distinct scopes (modules or weeks), whatever the language."""
        return len({scope for scope, _language in self.scopes})

    @property
    def kind(self) -> str:
        return self.kinds.most_common(1)[0][0] if self.kinds else "?"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "modules": self.modules,
            "courses": len(self.courses),
            "languages": sorted(self.languages),
            "kinds": dict(self.kinds),
            "queries": dict(self.queries.most_common()),
            "label": {"en": self.label_en, "fr": self.label_fr},
            "emoji": self.emoji,
            "library_match": self.match,
        }


@dataclass
class Inventory:
    by_head: dict[str, Tally] = field(default_factory=dict)
    by_query: dict[str, Tally] = field(default_factory=dict)
    documents: Counter = field(default_factory=Counter)
    scopes: set[tuple[str, str]] = field(default_factory=set)
    courses: set[str] = field(default_factory=set)
    skipped: int = 0

    def add(
        self,
        props: Any,
        *,
        scope: str,
        language: str,
        course: str | None,
        source: str,
    ) -> None:
        """Count the props of one document or plan."""
        self.documents[source] += 1
        for prop in props if isinstance(props, list) else []:
            query = prop.get("query") if isinstance(prop, dict) else None
            if not isinstance(query, str) or not normalise_query(query):
                self.skipped += 1
                continue
            phrase, head = normalise_query(query), head_noun(query)
            self.scopes.add((scope, language))
            if course:
                self.courses.add(course)
            for table, key in ((self.by_head, head), (self.by_query, phrase)):
                tally = table.setdefault(key, Tally(key=key))
                first = (scope, language) not in tally.scopes
                tally.scopes.add((scope, language))
                tally.languages.add(language)
                if course:
                    tally.courses.add(course)
                if first:
                    tally.kinds[str(prop.get("kind") or "?")] += 1
                    tally.queries[phrase] += 1
                en, fr = _labels(prop)
                tally.label_en = tally.label_en or en
                tally.label_fr = tally.label_fr or fr
                tally.emoji = tally.emoji or str(prop.get("emoji") or "")

    def ranked(self, table: dict[str, Tally]) -> list[Tally]:
        return sorted(table.values(), key=lambda t: (-t.modules, -len(t.courses), t.key))


def _labels(prop: dict[str, Any]) -> tuple[str, str]:
    """A prop's label: ``label.{en,fr}`` in a story, ``en``/``fr`` in a plan."""
    label = prop.get("label") if isinstance(prop.get("label"), dict) else prop
    en, fr = label.get("en"), label.get("fr")
    return (en if isinstance(en, str) else ""), (fr if isinstance(fr, str) else "")


def story_scope(module_id: Any, unit_id: Any, row_id: Any) -> tuple[str, str]:
    """The scope a story row counts in, and the kind of row it is."""
    if module_id:
        return f"module:{module_id}", "module story" if not unit_id else "chapter"
    if unit_id:
        return f"unit:{unit_id}", "chapter"
    return f"week:{row_id}", "hand-authored week"


# -- The library ------------------------------------------------------------------


def load_library(path: str) -> dict[str, str]:
    """Head noun → an example model name, from a JSON file of model names.

    Accepts a list of names, a list of ``{"name": ...}`` objects, or
    ``{"packs": {pack: [names]}}`` (as ``story_prop_candidates.json``); a
    name is indexed under each of its words, made singular.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    names: list[str] = []
    if isinstance(raw, dict) and isinstance(raw.get("packs"), dict):
        for pack, items in raw["packs"].items():
            names.extend(f"{pack}/{item}" for item in items if isinstance(item, str))
    elif isinstance(raw, list):
        for item in raw:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str):
                names.append(name)
    else:
        raise ValueError(f"{path}: expected a list of names or {{'packs': {{...}}}}")
    index: dict[str, str] = {}
    for name in names:
        for word in tokens(name.rsplit("/", 1)[-1]):
            index.setdefault(singular(word), name)
    return index


def match_library(inventory: Inventory, index: dict[str, str]) -> None:
    for table in (inventory.by_head, inventory.by_query):
        for tally in table.values():
            tally.match = index.get(
                head_noun(tally.key) if table is inventory.by_query else tally.key
            )


def hit_rate(tallies: Iterable[Tally], kind: str | None = None) -> tuple[int, int]:
    """(matched, total) prop uses (scope × language), optionally of one kind."""
    matched = total = 0
    for tally in tallies:
        if kind and tally.kind != kind:
            continue
        uses = len(tally.scopes)
        total += uses
        matched += uses if tally.match else 0
    return matched, total


# -- Database ---------------------------------------------------------------------


async def resolve_courses(session, refs: list[str]) -> dict[str, str]:
    """Course id → slug, for the ``--course`` filters (all courses without)."""
    rows = (await session.execute(select(Course.id, Course.slug))).all()
    courses = {str(course_id): slug for course_id, slug in rows}
    if not refs:
        return courses
    wanted = {ref.strip() for ref in refs}
    return {cid: slug for cid, slug in courses.items() if cid in wanted or slug in wanted}


def story_statement(*, published_only: bool):
    """Each story row's scope columns, course and ``content.props`` (not the document)."""
    statement = select(
        StoryCourseRecord.id,
        StoryCourseRecord.module_id,
        StoryCourseRecord.module_unit_id,
        StoryCourseRecord.language,
        func.coalesce(StoryCourseRecord.course_id, Module.course_id),
        StoryCourseRecord.status,
        StoryCourseRecord.content["props"],
    ).outerjoin(Module, Module.id == StoryCourseRecord.module_id)
    if published_only:
        statement = statement.where(StoryCourseRecord.status == "published")
    return statement


def plan_statement():
    """Each module plan's module, language, course and ``content.plan.props``."""
    return select(
        StoryModulePlan.module_id,
        StoryModulePlan.language,
        Module.course_id,
        StoryModulePlan.content["plan"]["props"],
    ).join(Module, Module.id == StoryModulePlan.module_id)


async def collect(
    session, *, course_refs: list[str], published_only: bool
) -> tuple[Inventory, dict]:
    """Read every story document's and plan's props into an :class:`Inventory`."""
    story_rows = (await session.execute(story_statement(published_only=published_only))).all()
    plan_rows = []
    if not published_only:
        plan_rows = (await session.execute(plan_statement())).all()
    courses = await resolve_courses(session, course_refs)
    if course_refs and not courses:
        raise LookupError(f"no course matches {', '.join(course_refs)}")

    inventory = Inventory()
    keep = (lambda cid: str(cid) in courses) if course_refs else (lambda _cid: True)
    for row_id, module_id, unit_id, language, course_id, _status, props in story_rows:
        if not keep(course_id):
            continue
        scope, source = story_scope(module_id, unit_id, row_id)
        inventory.add(
            props,
            scope=scope,
            language=language or "?",
            course=str(course_id) if course_id else None,
            source=source,
        )
    for module_id, language, course_id, props in plan_rows:
        if not keep(course_id):
            continue
        inventory.add(
            props,
            scope=f"module:{module_id}",
            language=language or "?",
            course=str(course_id) if course_id else None,
            source="module plan",
        )
    return inventory, courses


# -- Report -----------------------------------------------------------------------


def _cut(text: str, width: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[: width - 1] + "…"


def report_lines(inventory: Inventory, *, top: int, library: bool) -> list[str]:
    heads, queries = inventory.ranked(inventory.by_head), inventory.ranked(inventory.by_query)
    docs = ", ".join(f"{count} {source}" for source, count in sorted(inventory.documents.items()))
    lines = [
        f"Read: {docs or 'nothing'}.",
        f"Props in {len({s for s, _ in inventory.scopes})} modules or weeks of "
        f"{len(inventory.courses)} courses: {len(queries)} search phrases, {len(heads)} head nouns"
        + (
            f" ({inventory.skipped} props without a search phrase skipped)."
            if inventory.skipped
            else "."
        ),
    ]
    kinds = Counter()
    for tally in heads:
        kinds[tally.kind] += len(tally.scopes)
    if kinds:
        lines.append("Uses by kind: " + ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ".")
    if library:
        for kind in (None, "sticker", "real"):
            matched, total = hit_rate(heads, kind)
            if total:
                lines.append(
                    f"Library match ({kind or 'all'} props, lexical estimate): "
                    f"{matched}/{total} uses = {100 * matched / total:.0f}%."
                )
    for title, table in (
        ("BY HEAD NOUN (the shopping list)", heads),
        ("BY SEARCH PHRASE", queries),
    ):
        shown = table if top <= 0 else table[:top]
        lines += ["", f"== {title}: {len(shown)} of {len(table)}"]
        header = f"{'#':>3} {'mod':>4} {'crs':>4} {'kind':8} {'prop':28} {'label (fr / en)':44}"
        lines.append(header + (" library" if library else ""))
        for rank, tally in enumerate(shown, 1):
            label = f"{tally.emoji} {tally.label_fr} / {tally.label_en}".strip()
            row = (
                f"{rank:>3} {tally.modules:>4} {len(tally.courses):>4} {tally.kind:8} "
                f"{_cut(tally.key, 28):28} {_cut(label, 44):44}"
            )
            if library:
                row += " " + (_cut(tally.match, 40) if tally.match else "-")
            lines.append(row.rstrip())
    return lines


def report_json(inventory: Inventory, *, filters: dict[str, Any], library: bool) -> dict[str, Any]:
    heads = inventory.ranked(inventory.by_head)
    summary: dict[str, Any] = {
        "documents": dict(inventory.documents),
        "modules_or_weeks": len({s for s, _ in inventory.scopes}),
        "courses": len(inventory.courses),
        "search_phrases": len(inventory.by_query),
        "head_nouns": len(inventory.by_head),
        "skipped": inventory.skipped,
    }
    if library:
        summary["library_hit_rate"] = {
            kind or "all": dict(zip(("matched", "total"), hit_rate(heads, kind), strict=True))
            for kind in (None, "sticker", "real")
        }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "filters": filters,
        "summary": summary,
        "by_head": [tally.as_dict() for tally in heads],
        "by_query": [tally.as_dict() for tally in inventory.ranked(inventory.by_query)],
    }


# -- CLI --------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--course", action="append", default=[], help="course slug or UUID (repeatable)"
    )
    parser.add_argument(
        "--published-only",
        action="store_true",
        help="published story documents only (module plans are left out)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP,
        help=f"rows per ranking, 0 for all (default {DEFAULT_TOP})",
    )
    parser.add_argument("--library", default=None, help="JSON file of model names to match against")
    parser.add_argument(
        "--json", dest="json_path", default=None, help="also write the full report here"
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if any(not re.fullmatch(r"[A-Za-z0-9._-]+", ref) for ref in args.course):
        print("--course takes a slug or a UUID", file=sys.stderr)
        return 2
    index = load_library(args.library) if args.library else None
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    async with session_factory() as session:
        try:
            inventory, _courses = await collect(
                session, course_refs=args.course, published_only=args.published_only
            )
        except LookupError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if index is not None:
        match_library(inventory, index)
    print("\n".join(report_lines(inventory, top=args.top, library=index is not None)))
    if args.json_path:
        filters = {
            "course": args.course,
            "published_only": args.published_only,
            "library": args.library,
        }
        Path(args.json_path).write_text(
            json.dumps(
                report_json(inventory, filters=filters, library=index is not None),
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"\nFull report written to {args.json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
