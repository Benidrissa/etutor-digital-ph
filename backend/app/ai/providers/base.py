"""Provider-agnostic LLM interface for content generation (#2443).

Mirrors the figure ``vision_provider.py`` (#2435) pattern: a ``Protocol`` plus
concrete provider classes. Lets content generation (lessons, quizzes, case
studies, syllabi, video scripts) run on Anthropic Claude OR any OpenAI-compatible
model (Moonshot Kimi, OpenRouter, OpenAI) behind one interface, selected at
runtime from the ``ai-model-content`` setting.

The interface normalizes the two things that differ across providers:
  * **tool use** — Anthropic ``tool_use`` blocks vs OpenAI ``tool_calls``; both
    surface as :class:`LLMResult.tool_calls`, and each provider knows how to
    re-encode an assistant turn + tool results back into its own message shape
    (so a multi-turn agent loop stays provider-agnostic).
  * **prompt caching** — Anthropic ``cache_control`` ephemeral blocks have no
    OpenAI equivalent; non-Anthropic providers strip them. ``supports_cache_control``
    lets callers keep the cache path on Anthropic and fall back elsewhere.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResult:
    """Normalized result of one ``complete()`` call.

    ``assistant_message`` is the provider-native message dict to append to the
    running ``messages`` history before sending tool results back — opaque to
    callers, consumed only by the same provider's ``build_tool_result_messages``.
    """

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # normalized: "tool_use" | "end_turn" | "max_tokens"
    usage: dict[str, Any] = field(default_factory=dict)
    assistant_message: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    """One LLM backend. Implementations: Anthropic, OpenAI-compatible."""

    supports_cache_control: bool
    is_anthropic: bool

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
    ) -> LLMResult: ...

    def stream(
        self,
        *,
        system: str | list[dict[str, Any]],
        user_message: str,
        max_tokens: int,
        temperature: float,
        model: str,
    ) -> AsyncGenerator[str, None]: ...

    def build_tool_result_messages(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Encode ``[{"tool_call_id": str, "content": str}, ...]`` as the
        next-turn message(s) in this provider's native shape."""
        ...


def flatten_system(system: str | list[dict[str, Any]]) -> str:
    """Collapse Anthropic cache_control system blocks into a plain string.

    Used by OpenAI-compatible providers, which take the system prompt as a
    single ``{"role": "system"}`` message and have no ``cache_control`` concept.
    """
    if isinstance(system, str):
        return system
    return "\n\n".join(block.get("text", "") for block in system if isinstance(block, dict))
