"""CostTracker — wraps AI API calls to capture token usage, calculate credits, and log usage.

Designed to be injected as an optional dependency so existing admin flows
(that do not pass a user_id) are unaffected.

Dependencies resolved at runtime (lazy imports) so this module can be imported
even before #608/#609/#612 DB migrations are applied.  When those tables are
not yet present the tracker logs the event but silently skips DB writes.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from app.domain.services.platform_settings_service import SettingsCache

if TYPE_CHECKING:
    from anthropic.types import Message as AnthropicMessage
    from openai.types import CreateEmbeddingResponse
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_CLAUDE_INPUT_USD_PER_1K = 0.003
_CLAUDE_OUTPUT_USD_PER_1K = 0.015
_EMBEDDING_USD_PER_1K = 0.00002


@runtime_checkable
class CreditServiceProtocol(Protocol):
    """Minimal interface expected from CreditService (#612)."""

    async def deduct(
        self,
        user_id: uuid.UUID,
        amount: int,
        reason: str,
        session: AsyncSession,
    ) -> None: ...


class CostTracker:
    """Wraps Claude/OpenAI API responses to track token usage and deduct credits.

    Usage
    -----
    Inject via constructor of any AI service::

        tracker = CostTracker(credit_service=credit_svc)
        response = await client.messages.create(...)
        await tracker.track_anthropic_call(response, user_id, "lesson", session)

    The *credit_service* parameter is optional so that admin/RAG flows that
    have no associated user continue to work without modification.
    """

    def __init__(
        self,
        credit_service: CreditServiceProtocol | None = None,
    ) -> None:
        self._credit_service = credit_service
        self._cache = SettingsCache.instance()

    def _rate_input(self) -> float:
        return float(self._cache.get("credits-per-1k-input-tokens", 1.0))

    def _rate_output(self) -> float:
        return float(self._cache.get("credits-per-1k-output-tokens", 3.0))

    def _rate_embedding(self) -> float:
        return float(self._cache.get("credits-per-1k-embedding-tokens", 0.1))

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, float]:
        """Preview the credit cost before issuing an API call.

        Args:
            input_tokens: Estimated input token count.
            output_tokens: Estimated output token count.

        Returns:
            Dict with ``credits`` (int ceiling) and ``cost_usd`` (float).
        """
        credits = self._calc_credits(
            input_tokens, output_tokens, self._rate_input(), self._rate_output()
        )
        cost_usd = (input_tokens / 1000) * _CLAUDE_INPUT_USD_PER_1K + (
            output_tokens / 1000
        ) * _CLAUDE_OUTPUT_USD_PER_1K
        return {"credits": credits, "cost_usd": round(cost_usd, 6)}

    async def track_anthropic_call(
        self,
        response: AnthropicMessage,
        user_id: uuid.UUID | None,
        context: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Extract usage from an Anthropic Message, log, and deduct credits.

        Args:
            response: The ``Message`` object returned by ``client.messages.create()``.
            user_id: UUID of the learner. ``None`` for admin/system flows.
            context: Human-readable call site label (e.g. ``"lesson"``, ``"quiz"``).
            session: Async DB session.  Required for DB writes; if ``None`` only logs.

        Returns:
            Dict summarising ``input_tokens``, ``output_tokens``, ``credits``, ``cost_usd``.
        """
        usage = response.usage
        input_tokens: int = getattr(usage, "input_tokens", 0)
        output_tokens: int = getattr(usage, "output_tokens", 0)

        credits = self._calc_credits(
            input_tokens, output_tokens, self._rate_input(), self._rate_output()
        )
        cost_usd = (input_tokens / 1000) * _CLAUDE_INPUT_USD_PER_1K + (
            output_tokens / 1000
        ) * _CLAUDE_OUTPUT_USD_PER_1K

        logger.info(
            "cost_tracker.anthropic",
            context=context,
            user_id=str(user_id) if user_id else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            credits=credits,
            cost_usd=round(cost_usd, 6),
        )

        if session is not None and user_id is not None:
            await self._write_usage_log(
                user_id=user_id,
                api_provider="anthropic",
                model=getattr(response, "model", "claude-sonnet-4-6"),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                credits=credits,
                cost_usd=cost_usd,
                context=context,
                session=session,
            )
            await self._deduct(user_id, credits, context, session)

        return {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "credits": credits,
            "cost_usd": round(cost_usd, 6),
        }

    async def track_embedding_call(
        self,
        response: CreateEmbeddingResponse,
        user_id: uuid.UUID | None,
        context: str,
        session: AsyncSession | None = None,
    ) -> dict[str, Any]:
        """Extract usage from an OpenAI embedding response, log, and deduct credits.

        Args:
            response: The ``CreateEmbeddingResponse`` from ``client.embeddings.create()``.
            user_id: UUID of the learner. ``None`` for RAG indexing flows.
            context: Human-readable label (e.g. ``"rag_index"``, ``"query_embed"``).
            session: Async DB session.

        Returns:
            Dict summarising ``total_tokens``, ``credits``, ``cost_usd``.
        """
        usage = getattr(response, "usage", None)
        total_tokens: int = getattr(usage, "total_tokens", 0) if usage else 0

        credits = self._calc_embedding_credits(total_tokens, self._rate_embedding())
        cost_usd = (total_tokens / 1000) * _EMBEDDING_USD_PER_1K

        logger.info(
            "cost_tracker.embedding",
            context=context,
            user_id=str(user_id) if user_id else None,
            total_tokens=total_tokens,
            credits=credits,
            cost_usd=round(cost_usd, 8),
        )

        if session is not None and user_id is not None:
            model = (
                getattr(getattr(response, "data", [None])[0], "object", "text-embedding-3-small")
                if getattr(response, "data", None)
                else "text-embedding-3-small"
            )
            await self._write_usage_log(
                user_id=user_id,
                api_provider="openai",
                model=model,
                input_tokens=total_tokens,
                output_tokens=0,
                credits=credits,
                cost_usd=cost_usd,
                context=context,
                session=session,
            )
            await self._deduct(user_id, credits, context, session)

        return {
            "total_tokens": total_tokens,
            "credits": credits,
            "cost_usd": round(cost_usd, 8),
        }

    async def _write_usage_log(
        self,
        user_id: uuid.UUID,
        api_provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        credits: int,
        cost_usd: float,
        context: str,
        session: AsyncSession,
    ) -> None:
        """Persist an api_usage_logs row (table created by migration #609).

        Silently skips if the table does not yet exist so the service can run
        before the migration is applied.
        """
        try:
            from sqlalchemy import text

            await session.execute(
                text(
                    """
                    INSERT INTO api_usage_logs
                        (id, user_id, api_provider, model,
                         input_tokens, output_tokens, credits_deducted,
                         cost_usd, context, created_at)
                    VALUES
                        (:id, :user_id, :api_provider, :model,
                         :input_tokens, :output_tokens, :credits,
                         :cost_usd, :context, :created_at)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(user_id),
                    "api_provider": api_provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "credits": credits,
                    "cost_usd": round(cost_usd, 8),
                    "context": context,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )
            await session.flush()
        except Exception as exc:
            logger.warning(
                "cost_tracker.usage_log_skipped",
                reason=str(exc),
                user_id=str(user_id),
                context=context,
            )

    async def _deduct(
        self,
        user_id: uuid.UUID,
        credits: int,
        context: str,
        session: AsyncSession,
    ) -> None:
        """Deduct credits via CreditService if injected, else log a warning."""
        if credits <= 0:
            return
        if self._credit_service is None:
            logger.warning(
                "cost_tracker.no_credit_service",
                user_id=str(user_id),
                credits=credits,
                context=context,
            )
            return
        try:
            await self._credit_service.deduct(
                user_id=user_id,
                amount=credits,
                reason=f"ai_call:{context}",
                session=session,
            )
        except Exception as exc:
            logger.error(
                "cost_tracker.deduct_failed",
                user_id=str(user_id),
                credits=credits,
                context=context,
                error=str(exc),
            )

    @staticmethod
    def _calc_credits(
        input_tokens: int,
        output_tokens: int,
        rate_in: float,
        rate_out: float,
    ) -> int:
        raw = (input_tokens / 1000) * rate_in + (output_tokens / 1000) * rate_out
        return math.ceil(raw)

    @staticmethod
    def _calc_embedding_credits(total_tokens: int, rate: float) -> int:
        raw = (total_tokens / 1000) * rate
        return math.ceil(raw)
