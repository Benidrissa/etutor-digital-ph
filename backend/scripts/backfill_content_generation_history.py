"""Backfill estimated Anthropic content-generation history into the ledger (#2639).

Lesson/quiz/case-study/flashcard generation discarded token usage before the
ledger shipped (#2631), so past periods drastically under-represent Anthropic
on the AI-cost dashboard while (over-priced) Kimi quality-agent history is
fully visible. This one-off inserts one *estimated* chat row per historical
``generated_content`` + ``generated_content_revisions`` row created before the
``--before`` cutoff (the #2631 deploy time — live recording covers everything
after it).

Estimates (documented, all rows carry cost_estimated=true):
* model:  claude-sonnet-4-6 — the long-standing ``ai-model-content`` default
* output: len(content JSON) / 4 chars-per-token
* input:  12,000 tokens — RAG excerpts + system prompt + template, the
          typical shape observed in live lesson_generation ledger rows

Guarded: refuses to run if estimated Anthropic content-gen chat rows already
exist in the ledger.

Run from backend/:
  python scripts/backfill_content_generation_history.py --before 2026-07-11T13:15:00 [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.ai.providers.pricing import estimate_cost_cents  # noqa: E402
from app.domain.models.ai_usage_event import AiUsageEvent  # noqa: E402
from app.infrastructure.persistence.database import async_session_factory  # noqa: E402

_MODEL = "claude-sonnet-4-6"
_INPUT_TOKENS_ESTIMATE = 12_000
_CHARS_PER_TOKEN = 4

_FEATURES = {
    "lesson": "lesson_generation",
    "quiz": "quiz_generation",
    "flashcard": "flashcard_generation",
    "case": "case_study",
}


def _event(feature: str, module_id, output_tokens: int, created_at) -> AiUsageEvent:
    usage = {"input_tokens": _INPUT_TOKENS_ESTIMATE, "output_tokens": output_tokens}
    cents, _ = estimate_cost_cents(model=_MODEL, operation="chat", usage=usage)
    return AiUsageEvent(
        id=uuid.uuid4(),
        provider="anthropic",
        model=_MODEL,
        operation="chat",
        feature=feature,
        module_id=module_id,
        input_tokens=_INPUT_TOKENS_ESTIMATE,
        output_tokens=output_tokens,
        cost_cents=cents,
        cost_estimated=True,
        api_key_source="platform",
        created_at=created_at,
    )


async def backfill(before: datetime, dry_run: bool) -> None:
    async with async_session_factory() as session:
        existing = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM ai_usage_events
                    WHERE operation = 'chat' AND provider = 'anthropic'
                      AND cost_estimated = true
                      AND feature IN ('lesson_generation', 'quiz_generation',
                                      'flashcard_generation', 'case_study')
                      AND created_at < :before
                    """
                ).bindparams(before=before)
            )
        ).scalar_one()
        if existing:
            print(f"{existing} estimated content-gen rows already present — refusing to backfill.")
            return

        events: list[AiUsageEvent] = []

        rows = await session.execute(
            text(
                """
                SELECT content_type, module_id, length(content::text) AS chars, generated_at
                FROM generated_content WHERE generated_at < :before
                """
            ).bindparams(before=before)
        )
        for r in rows:
            feature = _FEATURES.get(r.content_type, r.content_type)
            events.append(
                _event(feature, r.module_id, int((r.chars or 0) / _CHARS_PER_TOKEN), r.generated_at)
            )

        # Revisions = QA-triggered regenerations; each was a full content-model call.
        rows = await session.execute(
            text(
                """
                SELECT gcr.created_at, length(gcr.content::text) AS chars,
                       gc.content_type, gc.module_id
                FROM generated_content_revisions gcr
                JOIN generated_content gc ON gc.id = gcr.generated_content_id
                WHERE gcr.created_at < :before
                """
            ).bindparams(before=before)
        )
        for r in rows:
            feature = _FEATURES.get(r.content_type, r.content_type)
            events.append(
                _event(feature, r.module_id, int((r.chars or 0) / _CHARS_PER_TOKEN), r.created_at)
            )

        total = sum(float(e.cost_cents) for e in events)
        print(f"prepared {len(events)} estimated rows, ${total / 100:.2f} total")
        if dry_run:
            print("dry-run — nothing written")
            return
        session.add_all(events)
        await session.commit()
        print("backfill committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--before",
        type=datetime.fromisoformat,
        required=True,
        help="Deploy time of #2631 (UTC ISO) — live recording covers everything after.",
    )
    args = parser.parse_args()
    asyncio.run(backfill(args.before, args.dry_run))
