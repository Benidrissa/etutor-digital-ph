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
    "claude-opus-4-8": {"input": 500, "output": 2500, "cache_write": 625, "cache_read": 50},
    # Moonshot moonshot-v1-128k — $2.00 / $5.00 per 1M; auto context-cache hit
    # billed lower (cache_read ~$0.20/M, re-verify). Standard chat model: honors
    # arbitrary temperature + json_object (unlike the kimi-k2.6 reasoning model).
    "moonshot-v1-128k": {"input": 200, "output": 500, "cache_write": 0, "cache_read": 20},
    # Moonshot kimi-k2.6 reasoning model (256K context). Kimi K2-family public
    # rates: $0.60/M input (cache miss), $2.50/M output, $0.15/M cache hit.
    # The old placeholder mirrored moonshot-v1-128k and overstated Kimi spend
    # ~3-4× (#2639). Re-verify against the Kimi console when rates change.
    "kimi-k2.6": {"input": 60, "output": 250, "cache_write": 0, "cache_read": 15},
    # OpenAI chat + syllabus-summarizer models (#2629). Re-verify against
    # https://openai.com/api/pricing when models rotate.
    "gpt-5.4": {"input": 125, "output": 1000, "cache_write": 0, "cache_read": 12},
    "gpt-5.4-mini": {"input": 25, "output": 200, "cache_write": 0, "cache_read": 2},
    "gpt-5.4-nano": {"input": 5, "output": 40, "cache_write": 0, "cache_read": 1},
    "gpt-4o-mini": {"input": 15, "output": 60, "cache_write": 0, "cache_read": 7},
    # OpenAI embeddings — input-only billing.
    "text-embedding-3-small": {"input": 2, "output": 0, "cache_write": 0, "cache_read": 0},
    "text-embedding-3-large": {"input": 13, "output": 0, "cache_write": 0, "cache_read": 0},
}

_DEFAULT = {"input": 300, "output": 1500, "cache_write": 375, "cache_read": 30}

# Non-token operations (#2629). All values are estimates in cents; re-verify
# against vendor pricing pages when models rotate.
# (model, quality) -> cents per generated image. gpt-image-1 is billed per image
# by quality/size; the service generates 1536x1024 at quality=medium.
_IMAGE_PRICING_CENTS: dict[tuple[str, str], float] = {
    ("gpt-image-1", "low"): 1.6,
    ("gpt-image-1", "medium"): 6.3,
    ("gpt-image-1", "high"): 25.0,
}
_IMAGE_DEFAULT_CENTS = 6.3  # unknown image model/quality — flag estimated
# gpt-4o-mini-tts ≈ $0.015/min of audio ≈ 750 chars/min → ~2¢ per 1K input chars.
_TTS_CENTS_PER_1K_CHARS = 2.0
# whisper-1: $0.006/min.
_STT_CENTS_PER_MINUTE = 0.6
# gpt-realtime-mini blended (audio in+out) — rough per-minute estimate.
_REALTIME_CENTS_PER_MINUTE = 10.0


def get_pricing(model: str) -> dict[str, int]:
    return _PRICING.get(model, _DEFAULT)


def get_pricing_ex(model: str) -> tuple[dict[str, int], bool]:
    """Pricing row plus an ``is_estimated`` flag for unknown models.

    Unknown models are still costed at the Sonnet-equivalent default so spend
    is never silently zero, but callers persist the flag instead of passing the
    fallback off as exact (#2629).
    """
    row = _PRICING.get(model)
    if row is not None:
        return row, False
    return _DEFAULT, True


def _token_cost_cents(model: str, usage: dict[str, Any]) -> tuple[float, bool]:
    p, estimated = get_pricing_ex(model)
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cwrite = int(usage.get("cache_creation_input_tokens") or 0)
    cread = int(usage.get("cache_read_input_tokens") or 0)
    cents = (
        inp * p["input"] + out * p["output"] + cwrite * p["cache_write"] + cread * p["cache_read"]
    ) / 1_000_000
    return cents, estimated


def estimate_cost_cents(
    *,
    model: str,
    operation: str,
    usage: dict[str, Any] | None = None,
    images_count: int | None = None,
    image_quality: str = "medium",
    audio_seconds: int | None = None,
    characters: int | None = None,
) -> tuple[float, bool]:
    """Cost of one call in fractional cents for the AI usage ledger (#2629).

    Returns ``(cents, is_estimated)``. Token-based operations use the pricing
    table (estimated only when the model is unknown); image/tts/stt/realtime
    use the per-unit constants above and are inherently approximate except for
    the per-image table.
    """
    if operation in ("chat", "embedding"):
        return _token_cost_cents(model, usage or {})
    if operation == "image":
        row = _IMAGE_PRICING_CENTS.get((model, image_quality))
        if row is not None:
            return row * (images_count or 0), False
        return _IMAGE_DEFAULT_CENTS * (images_count or 0), True
    if operation == "tts":
        return _TTS_CENTS_PER_1K_CHARS * (characters or 0) / 1000, True
    if operation == "stt":
        return _STT_CENTS_PER_MINUTE * (audio_seconds or 0) / 60, True
    if operation == "realtime":
        return _REALTIME_CENTS_PER_MINUTE * (audio_seconds or 0) / 60, True
    return 0.0, True


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
