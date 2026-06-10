"""Shared fakes for the pluggable LLM provider in tutor tests (#2483).

The tutor send loop, compaction, and mini-quiz now go through
``resolve_provider(model).complete(...)`` instead of the Anthropic SDK directly.
These helpers let tests script a provider's ``complete()`` with normalized
``LLMResult`` objects — no SDK, no network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.ai.providers.base import LLMResult


def llm(text="", tool_calls=None, stop_reason=None) -> LLMResult:
    """Build a normalized LLMResult the way a provider's complete() would."""
    tcs = tool_calls or []
    return LLMResult(
        text=text,
        tool_calls=tcs,
        stop_reason=stop_reason or ("tool_use" if tcs else "end_turn"),
        assistant_message={"role": "assistant", "content": text},
    )


class FakeProvider:
    """Stand-in for a resolved LLMProvider — no SDK, no network."""

    is_anthropic = True
    supports_cache_control = True

    def __init__(self):
        self.complete = AsyncMock()
        self.build_tool_result_messages = MagicMock(
            side_effect=lambda results: [
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
        )
