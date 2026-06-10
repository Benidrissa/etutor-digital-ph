"""Per-model pricing for generation cost accounting (#2443).

Replaces the Sonnet-hardcoded constants in ``quality_agent_service``. Cents per
million tokens. ``cache_write`` / ``cache_read`` apply only to Anthropic prompt
caching; OpenAI-compatible providers report cached input under ``cache_read`` at
their own (lower) rate, or 0 when unsupported.

Re-verify against each vendor's official pricing when it changes.
"""

from __future__ import annotations

from typing import Any

# cents per 1M tokens: (input, output, cache_write, cache_read)
_PRICING: dict[str, dict[str, int]] = {
    "claude-sonnet-4-6": {"input": 300, "output": 1500, "cache_write": 375, "cache_read": 30},
    "claude-haiku-4-5": {"input": 100, "output": 500, "cache_write": 125, "cache_read": 10},
    "claude-opus-4-6": {"input": 500, "output": 2500, "cache_write": 625, "cache_read": 50},
    # Moonshot moonshot-v1-128k — $2.00 / $5.00 per 1M; auto context-cache hit
    # billed lower (cache_read ~$0.20/M, re-verify). Standard chat model: honors
    # arbitrary temperature + json_object (unlike the kimi-k2.6 reasoning model).
    "moonshot-v1-128k": {"input": 200, "output": 500, "cache_write": 0, "cache_read": 20},
    # Moonshot kimi-k2.6 reasoning model (256K context). Placeholder rates mirror
    # moonshot-v1-128k until confirmed.
    # TODO(pricing): replace with confirmed kimi-k2.6 rates from the Kimi console.
    "kimi-k2.6": {"input": 200, "output": 500, "cache_write": 0, "cache_read": 20},
}

_DEFAULT = {"input": 300, "output": 1500, "cache_write": 375, "cache_read": 30}


def get_pricing(model: str) -> dict[str, int]:
    return _PRICING.get(model, _DEFAULT)


def calculate_cost_cents(model: str, usage: dict[str, Any]) -> int:
    """Cost of one call in integer cents, using ``model``'s pricing table.

    ``usage`` keys: ``input_tokens``, ``output_tokens``,
    ``cache_creation_input_tokens``, ``cache_read_input_tokens``.
    """
    p = get_pricing(model)
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cwrite = int(usage.get("cache_creation_input_tokens") or 0)
    cread = int(usage.get("cache_read_input_tokens") or 0)
    cents = (
        inp * p["input"] + out * p["output"] + cwrite * p["cache_write"] + cread * p["cache_read"]
    ) / 1_000_000
    return int(round(cents))
