"""Reprice recorded AI usage after the #2639 pricing corrections.

Two defects inflated recorded Kimi/Moonshot costs ~8×:
1. kimi-k2.6 was priced with a placeholder 3-4× above its real rates.
2. OpenAI-compat providers report ``prompt_tokens`` INCLUSIVE of cached
   tokens, but the pricing formulas assume Anthropic semantics (input
   excludes cache reads) — cached spans were billed twice. Fixed at the
   provider (#2639); rows recorded before the fix still store
   cache-inclusive ``input_tokens``.

This script repairs history:
* ``ai_usage_events`` chat rows: normalize pre-fix moonshot/openai input
  (``input_tokens -= cache_read_tokens``, only for rows created before
  ``--before`` — the fix's deploy time — so it can't double-subtract),
  then recompute ``cost_cents`` from the stored tokens (idempotent).
* ``unit_quality_assessments``: same normalization for moonshot-family
  models (``tokens_in``), then recompute ``cost_cents``.

Run from backend/:
  python scripts/reprice_ai_usage.py --dry-run [--before 2026-07-13T00:00:00]
  python scripts/reprice_ai_usage.py --before 2026-07-13T00:00:00

Without ``--before`` only the (idempotent) cost recomputation runs.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.ai.providers.pricing import calculate_cost_cents, estimate_cost_cents  # noqa: E402
from app.domain.models.ai_usage_event import AiUsageEvent  # noqa: E402
from app.domain.models.course_quality import UnitQualityAssessment  # noqa: E402
from app.infrastructure.persistence.database import async_session_factory  # noqa: E402

# Providers whose pre-fix rows stored cache-inclusive input (OpenAI semantics).
_CACHE_INCLUSIVE_PROVIDERS = ("moonshot", "openai", "openrouter")
_MOONSHOT_MODEL_PREFIXES = ("kimi", "moonshot")


def _usage_dict(input_t, output_t, cread, cwrite) -> dict:
    return {
        "input_tokens": input_t or 0,
        "output_tokens": output_t or 0,
        "cache_read_input_tokens": cread or 0,
        "cache_creation_input_tokens": cwrite or 0,
    }


async def reprice(dry_run: bool, before: datetime | None) -> None:
    async with async_session_factory() as session:
        deltas: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # model -> [old, new]

        # ---- ai_usage_events chat rows -------------------------------
        rows = (
            (
                await session.execute(
                    select(AiUsageEvent).where(
                        AiUsageEvent.operation == "chat",
                    )
                )
            )
            .scalars()
            .all()
        )
        normalized = repriced = 0
        for ev in rows:
            if ev.input_tokens is None and ev.output_tokens is None:
                continue
            # Normalize pre-fix cache-inclusive input exactly once.
            if (
                before is not None
                and ev.provider in _CACHE_INCLUSIVE_PROVIDERS
                and (ev.cache_read_tokens or 0) > 0
                and ev.created_at is not None
                and ev.created_at.replace(tzinfo=None) < before
                and (ev.input_tokens or 0) >= ev.cache_read_tokens
            ):
                ev.input_tokens = (ev.input_tokens or 0) - ev.cache_read_tokens
                normalized += 1
            cents, _ = estimate_cost_cents(
                model=ev.model,
                operation="chat",
                usage=_usage_dict(
                    ev.input_tokens, ev.output_tokens, ev.cache_read_tokens, ev.cache_write_tokens
                ),
            )
            old = float(ev.cost_cents or 0)
            if abs(old - cents) >= 0.0001:
                deltas[ev.model][0] += old
                deltas[ev.model][1] += cents
                ev.cost_cents = cents
                repriced += 1

        # ---- unit_quality_assessments --------------------------------
        qa_rows = (await session.execute(select(UnitQualityAssessment))).scalars().all()
        qa_normalized = qa_repriced = 0
        for qa in qa_rows:
            model = qa.model or "claude-sonnet-4-6"
            if (
                before is not None
                and model.startswith(_MOONSHOT_MODEL_PREFIXES)
                and (qa.cache_read_tokens or 0) > 0
                and qa.created_at is not None
                and qa.created_at.replace(tzinfo=None) < before
                and (qa.tokens_in or 0) >= qa.cache_read_tokens
            ):
                qa.tokens_in = (qa.tokens_in or 0) - qa.cache_read_tokens
                qa_normalized += 1
            cents = calculate_cost_cents(
                model,
                _usage_dict(
                    qa.tokens_in, qa.tokens_out, qa.cache_read_tokens, qa.cache_write_tokens
                ),
            )
            old = int(qa.cost_cents or 0)
            if old != cents:
                deltas[f"qa:{model}"][0] += old
                deltas[f"qa:{model}"][1] += cents
                qa.cost_cents = cents
                qa_repriced += 1

        print(f"ai_usage_events: {normalized} inputs normalized, {repriced} repriced")
        print(f"unit_quality_assessments: {qa_normalized} normalized, {qa_repriced} repriced")
        for model, (old, new) in sorted(deltas.items(), key=lambda kv: -kv[1][0]):
            print(f"  {model:32s} ${old / 100:9.2f} -> ${new / 100:9.2f}")

        if dry_run:
            await session.rollback()
            print("dry-run — nothing written")
            return
        await session.commit()
        print("repricing committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--before",
        type=datetime.fromisoformat,
        default=None,
        help="Deploy time of the #2639 normalization fix (UTC ISO). Rows created "
        "before it get cache-inclusive input corrected; omit to only reprice.",
    )
    args = parser.parse_args()
    asyncio.run(reprice(args.dry_run, args.before))
