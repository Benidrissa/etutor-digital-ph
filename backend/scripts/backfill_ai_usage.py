"""One-time estimated backfill of ai_usage_events from historical tables (#2629).

Usage recording starts at deploy time; this script seeds the ledger with
*estimated* rows derived from what past activity left behind, so the admin AI
cost dashboard isn't empty on day one:

  * document_chunks         → rag_indexing embeddings (token_count per course/day)
  * generated_images        → image generation (incl. failed rows)
  * generated_audio         → lesson TTS (chars estimated from duration)
  * tutor_message_audio     → tutor TTS
  * qbank_question_audio    → qbank TTS
  * tutor_voice_sessions    → realtime voice minutes
  * unit_quality_assessments → quality agent chat calls (exact tokens/cost)

Every row is written with cost_estimated=true (except quality assessments) and
created_at copied from the source row. Guarded: refuses to run if the ledger
already contains rows, so it cannot double-insert.

Run from backend/:  uv run python scripts/backfill_ai_usage.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.ai.providers.pricing import estimate_cost_cents  # noqa: E402
from app.domain.models.ai_usage_event import AiUsageEvent  # noqa: E402
from app.infrastructure.persistence.database import async_session_factory  # noqa: E402

# Historical defaults — staging/prod have only ever billed these models for
# the corresponding operations.
_EMBEDDING_MODEL = "text-embedding-3-small"
_IMAGE_MODEL = "gpt-image-1"
_TTS_MODEL = "gpt-4o-mini-tts"
_REALTIME_MODEL = "gpt-realtime-mini"
# ~750 chars of script per minute of TTS audio (used to reverse duration→chars).
_TTS_CHARS_PER_SECOND = 12.5


def _event(**kwargs) -> AiUsageEvent:
    cents, _ = estimate_cost_cents(
        model=kwargs["model"],
        operation=kwargs["operation"],
        usage=kwargs.get("usage"),
        images_count=kwargs.get("images_count"),
        audio_seconds=kwargs.get("audio_seconds"),
        characters=kwargs.get("characters"),
    )
    usage = kwargs.pop("usage", None) or {}
    return AiUsageEvent(
        id=uuid.uuid4(),
        cost_cents=cents,
        cost_estimated=True,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        api_key_source="platform",
        **kwargs,
    )


async def backfill(dry_run: bool) -> None:
    async with async_session_factory() as session:
        existing = (
            await session.execute(text("SELECT count(*) FROM ai_usage_events"))
        ).scalar_one()
        if existing:
            print(f"ai_usage_events already has {existing} rows — refusing to backfill.")
            return

        events: list[AiUsageEvent] = []

        # 1. RAG indexing embeddings: one estimated row per course per day.
        rows = await session.execute(
            text(
                """
                SELECT dc.course_id, date_trunc('day', dc.created_at) AS day,
                       sum(dc.token_count) AS tokens, count(*) AS chunks,
                       max(dc.created_at) AS created_at
                FROM document_chunks dc
                GROUP BY dc.course_id, day
                """
            )
        )
        for r in rows:
            events.append(
                _event(
                    provider="openai",
                    model=_EMBEDDING_MODEL,
                    operation="embedding",
                    feature="rag_indexing",
                    course_id=r.course_id,
                    usage={"input_tokens": int(r.tokens or 0)},
                    request_count=max(1, int(r.chunks) // 100),
                    created_at=r.created_at,
                )
            )

        # 2. Generated images (success + failed attempts).
        rows = await session.execute(
            text(
                """
                SELECT module_id, status, created_at
                FROM generated_images
                """
            )
        )
        for r in rows:
            ok = r.status == "ready"
            events.append(
                _event(
                    provider="openai",
                    model=_IMAGE_MODEL,
                    operation="image",
                    feature="image_generation",
                    module_id=r.module_id,
                    images_count=1 if ok else None,
                    success=ok,
                    error_type=None if ok else "backfill_failed_status",
                    created_at=r.created_at,
                )
            )

        # 3. TTS audio tables — chars estimated from duration where available.
        for table, feature, duration_col in (
            ("generated_audio", "lesson_audio", "duration_seconds"),
            ("tutor_message_audio", "tutor_tts", "duration_seconds"),
            ("qbank_question_audio", "qbank_audio", "duration_seconds"),
        ):
            try:
                rows = (
                    await session.execute(
                        text(f"SELECT {duration_col} AS dur, created_at FROM {table}")
                    )
                ).all()
            except Exception:
                await session.rollback()
                print(f"skipping {table} (missing table/column)")
                continue
            for r in rows:
                chars = int((r.dur or 60) * _TTS_CHARS_PER_SECOND)
                events.append(
                    _event(
                        provider="openai",
                        model=_TTS_MODEL,
                        operation="tts",
                        feature=feature,
                        characters=chars,
                        created_at=r.created_at,
                    )
                )

        # 4. Realtime voice sessions.
        try:
            rows = (
                await session.execute(
                    text(
                        "SELECT user_id, duration_seconds, started_at FROM tutor_voice_sessions"
                    )
                )
            ).all()
        except Exception:
            await session.rollback()
            rows = []
        for r in rows:
            events.append(
                _event(
                    provider="openai",
                    model=_REALTIME_MODEL,
                    operation="realtime",
                    feature="voice_session",
                    user_id=r.user_id,
                    audio_seconds=r.duration_seconds or 0,
                    created_at=r.started_at,
                )
            )

        # 5. Quality agent — exact tokens and cost already persisted.
        rows = await session.execute(
            text(
                """
                SELECT model, tokens_in, tokens_out, cache_read_tokens,
                       cache_write_tokens, cost_cents, created_at
                FROM unit_quality_assessments
                """
            )
        )
        for r in rows:
            provider = "anthropic" if (r.model or "").startswith("claude") else "moonshot"
            events.append(
                AiUsageEvent(
                    id=uuid.uuid4(),
                    provider=provider,
                    model=r.model or "unknown",
                    operation="chat",
                    feature="quality_agent",
                    input_tokens=r.tokens_in,
                    output_tokens=r.tokens_out,
                    cache_read_tokens=r.cache_read_tokens,
                    cache_write_tokens=r.cache_write_tokens,
                    cost_cents=r.cost_cents or 0,
                    cost_estimated=False,
                    api_key_source="platform",
                    created_at=r.created_at,
                )
            )

        print(f"prepared {len(events)} backfill rows")
        if dry_run:
            print("dry-run — nothing written")
            return
        session.add_all(events)
        await session.commit()
        print("backfill committed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(backfill(args.dry_run))
