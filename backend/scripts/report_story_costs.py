#!/usr/bin/env python3
"""Where do the tokens of a module story go? (#2735)

For one module (and, optionally, the calls made since a time), the story calls
of the AI usage ledger by kind: calls, failed calls, input and output tokens,
cost in USD, mean output tokens per call. Repairs have their own line under the
kind they repair, with the repair rate (repair calls over first calls of that
kind). Rows with no kind are shown too (what no call site attributed). Rows are
limited to ``feature = story_generation``. The ledger has no run id: several
runs of a module add up unless ``--since`` is given.

Read-only: SELECTs only, no model call, no write. The database is the
application's own (``DATABASE_URL``). Usage (inside the backend container)::

    python scripts/report_story_costs.py <module-id>
    python scripts/report_story_costs.py <module-id> --since 2026-11-20T08:00:00+00:00 --markdown
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.domain.models.ai_usage_event import FEATURE_STORY_GENERATION, AiUsageEvent  # noqa: E402

NO_KIND = "(no kind)"
COLUMNS = (
    ("kind", "kind"),
    ("calls", "calls"),
    ("failed", "failed"),
    ("input_tokens", "input tokens"),
    ("output_tokens", "output tokens"),
    ("cost_usd", "cost USD"),
    ("mean_output", "mean output/call"),
    ("repair_rate", "repair rate"),
)


def _blank(kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "calls": 0,
        "failed": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_cents": 0.0,
    }


def _add(line: dict[str, Any], event: Mapping[str, Any]) -> None:
    line["calls"] += 1
    line["failed"] += 0 if event.get("success", True) else 1
    line["input_tokens"] += int(event.get("input_tokens") or 0)
    line["output_tokens"] += int(event.get("output_tokens") or 0)
    line["cost_cents"] += float(event.get("cost_cents") or 0)


def _finish(line: dict[str, Any], rate: str = "") -> dict[str, Any]:
    calls = line["calls"]
    return {
        **line,
        "cost_usd": f"{line['cost_cents'] / 100:.4f}",
        "mean_output": round(line["output_tokens"] / calls) if calls else 0,
        "repair_rate": rate,
    }


def build_report(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The report's lines (pure): per kind a first-calls line then a repair line, then the total.

    ``events``: mappings with ``call_kind``, ``is_repair``, ``success`` and the token and cost fields.
    """
    first: dict[str, dict[str, Any]] = {}
    repairs: dict[str, dict[str, Any]] = {}
    total = _blank("TOTAL")
    for event in events:
        kind = event.get("call_kind") or NO_KIND
        bucket = repairs if event.get("is_repair") else first
        _add(bucket.setdefault(kind, _blank(kind)), event)
        _add(total, event)
    lines: list[dict[str, Any]] = []
    for kind in sorted(set(first) | set(repairs)):
        n_first = first.get(kind, {}).get("calls", 0)
        n_repair = repairs.get(kind, {}).get("calls", 0)
        if kind in first:
            lines.append(_finish(first[kind]))
        if kind in repairs:
            rate = f"{n_repair / n_first:.2f}" if n_first else "n/a"
            lines.append(_finish({**repairs[kind], "kind": f"{kind} (repair)"}, rate))
    lines.append(_finish(total))
    return lines


def format_table(rows: Iterable[Mapping[str, Any]], *, markdown: bool = False) -> str:
    """The lines as an aligned text table, or a Markdown one for a GitHub comment."""
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
    parser.add_argument("module_id", type=uuid.UUID, help="the module's id")
    parser.add_argument(
        "--since", type=datetime.fromisoformat, help="only calls made at or after this time (ISO)"
    )
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table")
    return parser.parse_args(argv)


async def collect(
    session, module_id: uuid.UUID, *, since: datetime | None = None
) -> list[dict[str, Any]]:
    """The module's story-generation ledger rows (SELECTs only)."""
    E = AiUsageEvent
    statement = select(
        E.call_kind, E.is_repair, E.success, E.input_tokens, E.output_tokens, E.cost_cents
    ).where(E.module_id == module_id, E.feature == FEATURE_STORY_GENERATION)
    if since is not None:
        statement = statement.where(E.created_at >= since)
    return [dict(row._mapping) for row in (await session.execute(statement)).all()]


async def main(argv: list[str] | None = None, session_factory=None) -> int:
    args = parse_args(argv)
    if session_factory is None:
        from app.infrastructure.persistence.database import async_session_factory

        session_factory = async_session_factory
    async with session_factory() as session:
        events = await collect(session, args.module_id, since=args.since)
    if not events:
        print("No story call found for this module.", file=sys.stderr)
        return 1
    print(format_table(build_report(events), markdown=args.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
