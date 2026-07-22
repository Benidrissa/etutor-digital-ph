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

Backends that reject a forced single-tool ``tool_choice`` (Moonshot accepts only
``none``/``auto``) set ``supports_forced_tool_choice=False``; ``complete()`` then
emulates the forced tool with JSON mode and returns a synthetic ``ToolCall``.
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


def _with_system(system_text: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prepend a system message, but only when there is actual system content.

    OpenAI-compatible backends (Moonshot/Kimi, Gemini's compat endpoint) reject a
    request whose first message is a ``system`` role with empty content — e.g. Moonshot
    returns ``400 "the message at position 0 with role 'system' must not be empty"``.
    Callers that legitimately have no system prompt (e.g. image alt-text) must not be
    forced to send an empty one, so we omit the system message entirely in that case.
    """
    if system_text and system_text.strip():
        return [{"role": "system", "content": system_text}, *messages]
    return list(messages)


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


# kimi-k2.6 (and the kimi-k2.x reasoning family) reject arbitrary sampling
# params: temperature is *fixed* by the model (thinking mode → 1.0, non-thinking
# → 0.6) and thinking is ON by default. We disable thinking — cheaper, lower
# latency, and keeps the forced-tool/JSON-mode structured-output path reliable —
# which pins the accepted temperature to 0.6. The standard chat family
# (moonshot-v1-*) is unaffected and keeps arbitrary temperature + native JSON.
_KIMI_NON_THINKING_TEMPERATURE = 0.6


def _kimi_reasoning_overrides(model: str) -> tuple[float | None, dict[str, Any]]:
    """Return ``(effective_temperature, extra_body)`` for a model.

    For ``kimi-*`` reasoning models, force the non-thinking temperature and pass
    ``thinking: disabled`` via ``extra_body``. Empty/``None`` for every other
    model, leaving their call unchanged.
    """
    if (model or "").lower().startswith("kimi"):
        return _KIMI_NON_THINKING_TEMPERATURE, {"thinking": {"type": "disabled"}}
    return None, {}


class OpenAICompatLLMProvider:
    """Any OpenAI Chat Completions backend (Moonshot / OpenRouter / OpenAI)."""

    supports_cache_control = False
    is_anthropic = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        supports_forced_tool_choice: bool = True,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)
        # Moonshot accepts only tool_choice none/auto — never a forced single
        # tool. When False, complete() emulates a forced tool via JSON mode.
        self._supports_forced_tool_choice = supports_forced_tool_choice

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
        system_text = flatten_system(system)

        # A forced single-tool call the backend can't express (Moonshot) is
        # emulated with JSON mode: ask for a JSON object matching the tool's
        # input_schema, then surface the parsed object as a synthetic ToolCall
        # so call sites keep reading result.tool_calls[0] unchanged.
        forced_name = (
            tool_choice.get("name") if tool_choice and tool_choice.get("type") == "tool" else None
        )
        emulate_tool = bool(forced_name and tools and not self._supports_forced_tool_choice)

        eff_temperature, extra_body = _kimi_reasoning_overrides(model)
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": eff_temperature if eff_temperature is not None else temperature,
        }
        if extra_body:
            kwargs["extra_body"] = extra_body
        if emulate_tool:
            forced_tool = next((t for t in tools if t.get("name") == forced_name), tools[0])
            schema = forced_tool.get("input_schema", {"type": "object", "properties": {}})
            system_text += (
                f"\n\nRespond with ONLY a single JSON object — no prose, no markdown — that "
                f"conforms to this JSON schema for `{forced_name}`:\n"
                f"{json.dumps(schema, ensure_ascii=False)}"
            )
            kwargs["response_format"] = {"type": "json_object"}
        elif tools:
            kwargs["tools"] = _to_openai_tools(tools)
            if tool_choice:
                kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)
        elif json_object:
            # response_format and forced-tool calls are mutually exclusive; the
            # forced tool already constrains the output shape.
            kwargs["response_format"] = {"type": "json_object"}

        kwargs["messages"] = _with_system(system_text, messages)

        response = await self._client.chat.completions.create(**kwargs)
        msg = response.choices[0].message
        content = msg.content or ""

        usage = getattr(response, "usage", None)
        cached = 0
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", 0) or 0
        # OpenAI-compat providers report prompt_tokens INCLUSIVE of cached
        # tokens, while the normalized dict follows Anthropic semantics where
        # input_tokens EXCLUDES cache reads — the pricing formulas
        # (calculate_cost_cents / estimate_cost_cents) add cache_read on top of
        # input, so leaving prompt_tokens raw double-billed the cached span
        # (#2639).
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        input_tokens = prompt_tokens - cached if prompt_tokens is not None else None
        usage_dict = {
            "input_tokens": input_tokens,
            "output_tokens": getattr(usage, "completion_tokens", None),
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": cached,
        }

        if emulate_tool:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("emulated forced-tool JSON not parseable", name=forced_name)
                return LLMResult(
                    text=content,
                    tool_calls=[],
                    stop_reason="end_turn",
                    usage=usage_dict,
                    assistant_message={"role": "assistant", "content": content},
                )
            synthetic = ToolCall(id=f"call_{forced_name}", name=forced_name, input=parsed)
            return LLMResult(
                text="",
                tool_calls=[synthetic],
                stop_reason="tool_use",
                usage=usage_dict,
                assistant_message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": synthetic.id,
                            "type": "function",
                            "function": {"name": forced_name, "arguments": content},
                        }
                    ],
                },
            )

        tool_calls: list[ToolCall] = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                logger.warning("tool_call arguments not valid JSON", name=tc.function.name)
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=args))

        assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
        if msg.tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]

        return LLMResult(
            text=content,
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
        usage_out: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        eff_temperature, extra_body = _kimi_reasoning_overrides(model)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": eff_temperature if eff_temperature is not None else temperature,
            "messages": _with_system(
                flatten_system(system),
                [{"role": "user", "content": user_message}],
            ),
            "stream": True,
        }
        if extra_body:
            create_kwargs["extra_body"] = extra_body
        stream = await self._client.chat.completions.create(**create_kwargs)
        async for chunk in stream:
            # Some OpenAI-compatible backends attach usage to a chunk (OpenAI
            # only with stream_options, which Moonshot/OpenRouter may reject —
            # so it isn't requested; capture opportunistically). Same
            # cached-token normalization as complete() (#2639).
            u = getattr(chunk, "usage", None)
            if usage_out is not None and u is not None:
                details = getattr(u, "prompt_tokens_details", None)
                cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
                prompt_tokens = getattr(u, "prompt_tokens", None)
                usage_out.update(
                    input_tokens=prompt_tokens - cached if prompt_tokens is not None else None,
                    output_tokens=getattr(u, "completion_tokens", None),
                    cache_creation_input_tokens=0,
                    cache_read_input_tokens=cached,
                )
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def build_tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"role": "tool", "tool_call_id": r["tool_call_id"], "content": r["content"]}
            for r in results
        ]
