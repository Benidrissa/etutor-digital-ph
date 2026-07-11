"""Usage-recording decorator around any LLMProvider (#2629).

Wired once in :func:`app.ai.providers.registry.resolve_provider`, so every chat
call site in the repo gets a ledger row without touching the call sites. The
wrapper is transparent: results and exceptions pass through unchanged; recording
failures are swallowed inside :func:`record_ai_usage`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from typing import Any

from app.ai.providers.base import LLMProvider, LLMResult

# ~4 chars/token — rough output-token estimate for streamed responses, whose
# providers never surface usage counts.
_CHARS_PER_TOKEN = 4


class RecordingLLMProvider:
    """Delegates to ``inner``, recording one AiUsageEvent per call."""

    def __init__(self, inner: LLMProvider, provider_name: str) -> None:
        self._inner = inner
        self._provider_name = provider_name

    @property
    def supports_cache_control(self) -> bool:
        return self._inner.supports_cache_control

    @property
    def is_anthropic(self) -> bool:
        return self._inner.is_anthropic

    async def complete(
        self,
        *,
        system: str | list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
        json_object: bool = False,
    ) -> LLMResult:
        from app.domain.services.ai_usage_service import record_ai_usage

        started = time.monotonic()
        try:
            result = await self._inner.complete(
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
                tools=tools,
                tool_choice=tool_choice,
                json_object=json_object,
            )
        except Exception as exc:
            await record_ai_usage(
                provider=self._provider_name,
                model=model,
                operation="chat",
                duration_ms=int((time.monotonic() - started) * 1000),
                success=False,
                error_type=type(exc).__name__,
            )
            raise
        await record_ai_usage(
            provider=self._provider_name,
            model=model,
            operation="chat",
            usage=result.usage,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        return result

    async def stream(
        self,
        *,
        system: str | list[dict[str, Any]],
        user_message: str,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AsyncGenerator[str, None]:
        from app.domain.services.ai_usage_service import record_ai_usage

        started = time.monotonic()
        chars = 0
        try:
            async for chunk in self._inner.stream(
                system=system,
                user_message=user_message,
                max_tokens=max_tokens,
                temperature=temperature,
                model=model,
            ):
                chars += len(chunk)
                yield chunk
        except Exception as exc:
            await record_ai_usage(
                provider=self._provider_name,
                model=model,
                operation="chat",
                characters=chars,
                duration_ms=int((time.monotonic() - started) * 1000),
                success=False,
                error_type=type(exc).__name__,
            )
            raise
        # Streaming never surfaces token usage — estimate output tokens from chars.
        await record_ai_usage(
            provider=self._provider_name,
            model=model,
            operation="chat",
            usage={"output_tokens": chars // _CHARS_PER_TOKEN},
            characters=chars,
            duration_ms=int((time.monotonic() - started) * 1000),
            cost_estimated=True,
        )

    def build_tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._inner.build_tool_result_messages(results)
