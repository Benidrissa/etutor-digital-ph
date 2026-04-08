"""Model capabilities registry for token-aware budget calculations.

Maps Claude model IDs to their context window, max output tokens,
and chars-per-token ratio for FR/EN mixed text.

Why ratio-based (not tiktoken):
  The RAG chunker uses cl100k_base (GPT-4 tokenizer, not Claude's).
  For budget estimation where 10% error is acceptable, a ratio is
  simpler and faster than encoding megabytes of text.
"""

from __future__ import annotations

_MODEL_CAPABILITIES: dict[str, dict] = {
    "gpt-5.4-nano": {
        "context_window_tokens": 272_000,
        "max_output_tokens": 16_384,
        "chars_per_token": 4.0,
    },
    "claude-sonnet-4-6": {
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 64_000,
        "chars_per_token": 3.5,
    },
    "claude-opus-4-6": {
        "context_window_tokens": 1_000_000,
        "max_output_tokens": 128_000,
        "chars_per_token": 3.5,
    },
    "claude-haiku-4-5": {
        "context_window_tokens": 200_000,
        "max_output_tokens": 64_000,
        "chars_per_token": 3.5,
    },
    "_default": {
        "context_window_tokens": 200_000,
        "max_output_tokens": 8_000,
        "chars_per_token": 4.0,
    },
}


def get_model_caps(model: str) -> dict:
    """Return capabilities dict for the given model, falling back to _default."""
    return _MODEL_CAPABILITIES.get(model, _MODEL_CAPABILITIES["_default"])


def chars_to_tokens(chars: int, model: str) -> int:
    """Estimate token count from character count for the given model."""
    caps = get_model_caps(model)
    return int(chars / caps["chars_per_token"])


def tokens_to_chars(tokens: int, model: str) -> int:
    """Estimate character count from token count for the given model."""
    caps = get_model_caps(model)
    return int(tokens * caps["chars_per_token"])
