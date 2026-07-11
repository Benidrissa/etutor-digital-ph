"""AI usage ledger — recorder, aggregations, and money-saving recommendations (#2629).

``record_ai_usage`` is the single write path for :class:`AiUsageEvent` rows. It
is fire-and-forget by contract: it opens its own short-lived session (never the
caller's), swallows every exception, and adds ~1ms to calls that take seconds —
so it is awaited inline from providers, embeddings, image/TTS/STT clients.
Attribution context (feature/user/course/module) comes from
:mod:`app.ai.usage_context` unless passed explicitly.

``AiUsageAnalyticsService`` serves ``GET /analytics/ai-usage``;
``build_recommendations`` is a pure function over the aggregates so the advice
rules are unit-testable without a database.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.pricing import estimate_cost_cents
from app.ai.usage_context import current_ai_context
from app.domain.models.ai_usage_event import FEATURE_UNKNOWN, AiUsageEvent
from app.domain.models.user import User

logger = structlog.get_logger(__name__)

# Providers that support tenant key overrides (ApiKeyService.PROVIDERS subset).
_KEYED_PROVIDERS = {"anthropic", "openai", "google", "moonshot"}


def _api_key_source(provider: str) -> str:
    if provider not in _KEYED_PROVIDERS:
        return "platform"
    from app.domain.services.api_key_service import ApiKeyService

    return ApiKeyService.source(provider)


def _tracking_enabled() -> bool:
    from app.infrastructure.config.settings import get_settings

    return bool(getattr(get_settings(), "ai_usage_tracking_enabled", True))


async def record_ai_usage(
    *,
    provider: str,
    model: str,
    operation: str,
    usage: dict[str, Any] | None = None,
    images_count: int | None = None,
    image_quality: str = "medium",
    audio_seconds: int | None = None,
    characters: int | None = None,
    duration_ms: int | None = None,
    success: bool = True,
    error_type: str | None = None,
    request_count: int = 1,
    cost_estimated: bool | None = None,
    feature: str | None = None,
    user_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    module_id: uuid.UUID | None = None,
) -> None:
    """Persist one ledger row. Never raises; never touches the caller's session."""
    try:
        if not _tracking_enabled():
            return
        ctx = current_ai_context()
        cents, estimated = estimate_cost_cents(
            model=model,
            operation=operation,
            usage=usage,
            images_count=images_count,
            image_quality=image_quality,
            audio_seconds=audio_seconds,
            characters=characters,
        )
        usage = usage or {}
        event = AiUsageEvent(
            id=uuid.uuid4(),
            provider=provider,
            model=model[:100],
            operation=operation,
            feature=(feature or ctx.feature or FEATURE_UNKNOWN)[:50],
            user_id=user_id or ctx.user_id,
            course_id=course_id or ctx.course_id,
            module_id=module_id or ctx.module_id,
            api_key_source=_api_key_source(provider),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            cache_read_tokens=usage.get("cache_read_input_tokens"),
            cache_write_tokens=usage.get("cache_creation_input_tokens"),
            images_count=images_count,
            audio_seconds=audio_seconds,
            characters=characters,
            request_count=request_count,
            cost_cents=cents,
            cost_estimated=estimated if cost_estimated is None else cost_estimated,
            duration_ms=duration_ms,
            success=success,
            error_type=error_type[:100] if error_type else None,
        )
        from app.infrastructure.persistence.database import async_session_factory

        async with async_session_factory() as session:
            session.add(event)
            await session.commit()
    except Exception as exc:  # pragma: no cover - by-contract swallow
        logger.warning(
            "ai_usage.record_failed", provider=provider, model=model, error=str(exc)
        )


@dataclass
class AiUsageAggregates:
    """Aggregate inputs to the recommendation rules (period-scoped)."""

    total_cost_cents: float = 0.0
    estimated_cost_cents: float = 0.0
    total_calls: int = 0
    error_calls: int = 0
    failed_cost_cents: float = 0.0
    chat_cost_cents: float = 0.0
    # chat cost per model, e.g. {"claude-opus-4-8": 812.5}
    chat_cost_by_model: dict[str, float] = field(default_factory=dict)
    estimated_models: list[str] = field(default_factory=list)
    courses_reindexed: int = 0
    reindex_cost_cents: float = 0.0
    image_fallback_failures: int = 0
    image_openai_successes: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    anthropic_input_tokens: int = 0
    tenant_key_calls: int = 0


def build_recommendations(agg: AiUsageAggregates) -> list[dict[str, Any]]:
    """Rule-based money-saving advice. Codes only — the frontend translates."""
    recos: list[dict[str, Any]] = []

    if agg.total_cost_cents > 0:
        est_share = agg.estimated_cost_cents / agg.total_cost_cents
        if est_share > 0.10 and agg.estimated_models:
            recos.append(
                {
                    "code": "add_pricing_for_models",
                    "severity": "info",
                    "data": {
                        "share": round(est_share, 2),
                        "models": agg.estimated_models[:5],
                    },
                }
            )

    if agg.chat_cost_cents > 0:
        expensive = {
            m: c
            for m, c in agg.chat_cost_by_model.items()
            if m.startswith(("claude-opus", "claude-sonnet"))
        }
        share = sum(expensive.values()) / agg.chat_cost_cents
        if share > 0.60 and expensive:
            top = max(expensive, key=lambda m: expensive[m])
            recos.append(
                {
                    "code": "expensive_model_share",
                    "severity": "warning",
                    "data": {"share": round(share, 2), "model": top},
                }
            )
        gpt_share = sum(
            c for m, c in agg.chat_cost_by_model.items() if m.startswith("gpt")
        ) / agg.chat_cost_cents
        if gpt_share > 0.40:
            recos.append(
                {
                    "code": "provider_alternative",
                    "severity": "info",
                    "data": {"share": round(gpt_share, 2)},
                }
            )

    if agg.courses_reindexed > 0:
        recos.append(
            {
                "code": "reindexing_waste",
                "severity": "warning",
                "data": {
                    "courses": agg.courses_reindexed,
                    "cost_cents": round(agg.reindex_cost_cents, 2),
                },
            }
        )

    if agg.total_calls > 0 and (
        agg.error_calls / agg.total_calls > 0.05 or agg.failed_cost_cents > 100
    ):
        recos.append(
            {
                "code": "failed_spend",
                "severity": "warning",
                "data": {
                    "errors": agg.error_calls,
                    "cost_cents": round(agg.failed_cost_cents, 2),
                },
            }
        )

    if agg.image_fallback_failures > 0 and agg.image_openai_successes > 0:
        recos.append(
            {
                "code": "image_fallback_active",
                "severity": "warning",
                "data": {"failures": agg.image_fallback_failures},
            }
        )

    cached_input = agg.anthropic_input_tokens + agg.cache_read_tokens
    if agg.cache_write_tokens > 100_000 and cached_input > 0:
        reuse = agg.cache_read_tokens / cached_input
        if reuse < 0.20:
            recos.append(
                {
                    "code": "low_cache_reuse",
                    "severity": "info",
                    "data": {"reuse": round(reuse, 2)},
                }
            )

    if agg.total_calls > 0 and agg.tenant_key_calls == 0:
        recos.append({"code": "platform_key_only", "severity": "info", "data": {}})

    return recos


class AiUsageAnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_ai_usage(self, period_days: int) -> dict[str, Any]:
        since = datetime.now(tz=UTC) - timedelta(days=period_days)
        E = AiUsageEvent

        totals_row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(E.cost_cents), 0).label("cost"),
                    func.count(E.id).label("calls"),
                    func.coalesce(
                        func.sum(case((E.success.is_(False), 1), else_=0)), 0
                    ).label("errors"),
                    func.coalesce(
                        func.sum(case((E.success.is_(False), E.cost_cents), else_=0)), 0
                    ).label("failed_cost"),
                    func.coalesce(
                        func.sum(case((E.cost_estimated.is_(True), E.cost_cents), else_=0)),
                        0,
                    ).label("estimated_cost"),
                    func.coalesce(func.sum(E.input_tokens), 0).label("input_tokens"),
                    func.coalesce(func.sum(E.output_tokens), 0).label("output_tokens"),
                    func.coalesce(func.sum(E.cache_read_tokens), 0).label("cache_read"),
                    func.coalesce(func.sum(E.cache_write_tokens), 0).label("cache_write"),
                ).where(E.created_at >= since)
            )
        ).one()

        daily_rows = (
            await self.db.execute(
                select(
                    func.date_trunc("day", E.created_at).label("day"),
                    E.provider,
                    func.sum(E.cost_cents).label("cost"),
                )
                .where(E.created_at >= since)
                .group_by("day", E.provider)
                .order_by("day")
            )
        ).all()
        daily_map: dict[str, dict[str, Any]] = {}
        for row in daily_rows:
            day = str(row.day.date())
            daily_map.setdefault(day, {"date": day})[row.provider] = float(row.cost)
        daily_costs = list(daily_map.values())

        by_model_rows = (
            await self.db.execute(
                select(
                    E.model,
                    E.provider,
                    func.count(E.id).label("calls"),
                    func.coalesce(func.sum(E.input_tokens), 0).label("input_tokens"),
                    func.coalesce(func.sum(E.output_tokens), 0).label("output_tokens"),
                    func.sum(E.cost_cents).label("cost"),
                    func.bool_or(E.cost_estimated).label("estimated"),
                )
                .where(E.created_at >= since)
                .group_by(E.model, E.provider)
                .order_by(func.sum(E.cost_cents).desc())
            )
        ).all()
        by_model = [
            {
                "model": r.model,
                "provider": r.provider,
                "calls": r.calls,
                "input_tokens": int(r.input_tokens),
                "output_tokens": int(r.output_tokens),
                "cost_cents": float(r.cost),
                "estimated": bool(r.estimated),
            }
            for r in by_model_rows
        ]

        by_feature_rows = (
            await self.db.execute(
                select(
                    E.feature,
                    func.count(E.id).label("calls"),
                    func.sum(E.cost_cents).label("cost"),
                    func.coalesce(
                        func.sum(
                            func.coalesce(E.input_tokens, 0) + func.coalesce(E.output_tokens, 0)
                        ),
                        0,
                    ).label("tokens"),
                )
                .where(E.created_at >= since)
                .group_by(E.feature)
                .order_by(func.sum(E.cost_cents).desc())
            )
        ).all()
        by_feature = [
            {
                "feature": r.feature,
                "calls": r.calls,
                "cost_cents": float(r.cost),
                "tokens": int(r.tokens),
            }
            for r in by_feature_rows
        ]

        by_user_rows = (
            await self.db.execute(
                select(
                    E.user_id,
                    User.email,
                    func.count(E.id).label("calls"),
                    func.sum(E.cost_cents).label("cost"),
                )
                .join(User, User.id == E.user_id)
                .where(E.created_at >= since, E.user_id.is_not(None))
                .group_by(E.user_id, User.email)
                .order_by(func.sum(E.cost_cents).desc())
                .limit(10)
            )
        ).all()
        by_user = [
            {
                "user_id": str(r.user_id),
                "email": r.email,
                "calls": r.calls,
                "cost_cents": float(r.cost),
            }
            for r in by_user_rows
        ]

        by_source_rows = (
            await self.db.execute(
                select(
                    E.api_key_source,
                    func.count(E.id).label("calls"),
                    func.sum(E.cost_cents).label("cost"),
                )
                .where(E.created_at >= since)
                .group_by(E.api_key_source)
            )
        ).all()
        by_key_source = [
            {"source": r.api_key_source, "calls": r.calls, "cost_cents": float(r.cost)}
            for r in by_source_rows
        ]

        errors_rows = (
            await self.db.execute(
                select(
                    E.feature,
                    func.count(E.id).label("count"),
                    func.sum(E.cost_cents).label("cost"),
                )
                .where(E.created_at >= since, E.success.is_(False))
                .group_by(E.feature)
                .order_by(func.count(E.id).desc())
            )
        ).all()
        errors_by_feature = [
            {"feature": r.feature, "count": r.count, "cost_cents": float(r.cost)}
            for r in errors_rows
        ]

        # Courses whose resources were embedded for indexing more than once in
        # the period — repeat full re-embeds are the main embedding waste.
        reindex_sub = (
            select(E.course_id, func.sum(E.cost_cents).label("cost"))
            .where(
                E.created_at >= since,
                E.feature == "rag_indexing",
                E.operation == "embedding",
                E.course_id.is_not(None),
            )
            .group_by(E.course_id)
            .having(func.count(E.id) > 1)
            .subquery()
        )
        reindex_row = (
            await self.db.execute(
                select(
                    func.count().label("courses"),
                    func.coalesce(func.sum(reindex_sub.c.cost), 0).label("cost"),
                )
            )
        ).one()

        image_fallback_failures = (
            await self.db.execute(
                select(func.count(E.id)).where(
                    E.created_at >= since,
                    E.operation == "image",
                    E.provider == "google",
                    E.success.is_(False),
                )
            )
        ).scalar_one()
        image_openai_successes = (
            await self.db.execute(
                select(func.count(E.id)).where(
                    E.created_at >= since,
                    E.operation == "image",
                    E.provider == "openai",
                    E.success.is_(True),
                )
            )
        ).scalar_one()

        anthropic_input = (
            await self.db.execute(
                select(func.coalesce(func.sum(E.input_tokens), 0)).where(
                    E.created_at >= since, E.provider == "anthropic"
                )
            )
        ).scalar_one()

        total_cost = float(totals_row.cost)
        chat_rows = (
            await self.db.execute(
                select(E.model, func.sum(E.cost_cents).label("cost"))
                .where(E.created_at >= since, E.operation == "chat")
                .group_by(E.model)
            )
        ).all()
        chat_by_model = {r.model: float(r.cost) for r in chat_rows}
        tenant_calls = sum(r["calls"] for r in by_key_source if r["source"] == "tenant")

        agg = AiUsageAggregates(
            total_cost_cents=total_cost,
            estimated_cost_cents=float(totals_row.estimated_cost),
            total_calls=totals_row.calls,
            error_calls=int(totals_row.errors),
            failed_cost_cents=float(totals_row.failed_cost),
            chat_cost_cents=sum(chat_by_model.values()),
            chat_cost_by_model=chat_by_model,
            estimated_models=[r["model"] for r in by_model if r["estimated"]],
            courses_reindexed=int(reindex_row.courses),
            reindex_cost_cents=float(reindex_row.cost),
            image_fallback_failures=int(image_fallback_failures),
            image_openai_successes=int(image_openai_successes),
            cache_write_tokens=int(totals_row.cache_write),
            cache_read_tokens=int(totals_row.cache_read),
            anthropic_input_tokens=int(anthropic_input),
            tenant_key_calls=tenant_calls,
        )

        return {
            "period": f"{period_days}d",
            "totals": {
                "cost_cents": total_cost,
                "calls": totals_row.calls,
                "errors": int(totals_row.errors),
                "input_tokens": int(totals_row.input_tokens),
                "output_tokens": int(totals_row.output_tokens),
                "cache_read_tokens": int(totals_row.cache_read),
                "cache_write_tokens": int(totals_row.cache_write),
                "estimated_cost_share": (
                    round(float(totals_row.estimated_cost) / total_cost, 4)
                    if total_cost > 0
                    else 0.0
                ),
            },
            "top_model": by_model[0]["model"] if by_model else None,
            "daily_costs": daily_costs,
            "by_model": by_model,
            "by_feature": by_feature,
            "by_user": by_user,
            "by_key_source": by_key_source,
            "errors_by_feature": errors_by_feature,
            "recommendations": build_recommendations(agg),
        }
