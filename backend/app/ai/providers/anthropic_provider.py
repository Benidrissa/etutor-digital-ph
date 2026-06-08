"""Anthropic Claude provider (#2443).

Wraps ``anthropic.AsyncAnthropic``. Preserves every Anthropic-native feature the
codebase already relies on: ``cache_control`` ephemeral system blocks, ``tool_use``
structured output, and streamed text. ``complete()`` always goes through
``messages.stream`` + ``get_final_message`` so large ``max_tokens`` requests (e.g.
64k syllabus generation) don't trip the SDK's non-streaming timeout guard.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import anthropic
import structlog

from app.ai.providers.base import LLMResult, ToolCall

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 600.0


class AnthropicLLMProvider:
    """Claude via the Anthropic Messages API."""

    supports_cache_control = True
    is_anthropic = True

    def __init__(self, *, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS)

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
        json_object: bool = False,  # noqa: ARG002 — Anthropic uses prompt-driven JSON
    ) -> LLMResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        async with self._client.messages.stream(**kwargs) as stream:
            message = await stream.get_final_message()

        text = "".join(b.text for b in message.content if getattr(b, "type", None) == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=dict(b.input or {}))
            for b in message.content
            if getattr(b, "type", None) == "tool_use"
        ]
        usage = getattr(message, "usage", None)
        usage_dict = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
        }
        return LLMResult(
            text=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else (message.stop_reason or "end_turn"),
            usage=usage_dict,
            assistant_message={"role": "assistant", "content": message.content},
        )

    async def stream(
        self,
        *,
        system: str | list[dict[str, Any]],
        user_message: str,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AsyncGenerator[str, None]:
        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
            temperature=temperature,
        ) as stream_manager:
            async for event in stream_manager:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield event.delta.text

    def build_tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": r["tool_call_id"],
                        "content": r["content"],
                    }
                    for r in results
                ],
            }
        ]
