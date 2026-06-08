"""OpenAI-compatible provider (#2443).

Serves Moonshot Kimi (``base_url=https://api.moonshot.ai/v1``), OpenRouter, and
OpenAI behind the Chat Completions API — same ``AsyncOpenAI`` client the
embeddings service and ``vision_provider`` already depend on (no new package).

Normalizes the OpenAI surface to the provider interface:
  * system blocks (incl. Anthropic ``cache_control``) → one ``system`` message,
    cache_control stripped (these providers do their own automatic prefix caching);
  * Anthropic tool schema → ``{"type": "function", "function": {...}}``;
  * ``tool_calls`` (arguments JSON string) → :class:`ToolCall`;
  * ``prompt_tokens`` / ``completion_tokens`` → ``input_tokens`` / ``output_tokens``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from openai import AsyncOpenAI

from app.ai.providers.base import LLMResult, ToolCall, flatten_system

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 600.0


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic ``{name, description, input_schema}`` → OpenAI function tool."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _to_openai_tool_choice(tool_choice: dict[str, Any]) -> Any:
    """Anthropic ``{"type": "tool", "name": X}`` → OpenAI forced-function choice."""
    if tool_choice.get("type") == "tool" and tool_choice.get("name"):
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    if tool_choice.get("type") == "any":
        return "required"
    return "auto"


class OpenAICompatLLMProvider:
    """Any OpenAI Chat Completions backend (Moonshot / OpenRouter / OpenAI)."""

    supports_cache_control = False
    is_anthropic = False

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)

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
        msgs = [{"role": "system", "content": flatten_system(system)}, *messages]
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": msgs,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)
            if tool_choice:
                kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)
        elif json_object:
            # response_format and forced-tool calls are mutually exclusive; the
            # forced tool already constrains the output shape.
            kwargs["response_format"] = {"type": "json_object"}

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                logger.warning("tool_call arguments not valid JSON", name=tc.function.name)
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        assistant_message: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]

        usage = getattr(response, "usage", None)
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        usage_dict = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cached,
        }
        return LLMResult(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=usage_dict,
            assistant_message=assistant_message,
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
        stream = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": flatten_system(system)},
                {"role": "user", "content": user_message},
            ],
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def build_tool_result_messages(
        self, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            {"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]}
            for r in results
        ]
