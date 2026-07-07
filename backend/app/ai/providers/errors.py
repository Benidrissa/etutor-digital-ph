"""Provider error classification (#2571).

Upstream LLM failures used to surface as an opaque ``502 AI generation failed``
even when the real cause was the provider account itself (quota exhausted,
suspended for insufficient balance, bad API key) — an admin/config problem, not
a platform bug. ``classify_provider_error`` inspects the raw SDK exception so
call sites can return an interpretable error instead.

Provider-agnostic by duck-typing: both the Anthropic and OpenAI SDKs expose
``status_code`` on their ``APIStatusError`` families, and the billing/auth
signal is carried in the message body text.
"""

from __future__ import annotations

from enum import StrEnum


class ProviderErrorKind(StrEnum):
    QUOTA = "quota"
    AUTH = "auth"
    UNKNOWN = "unknown"


# Body-text markers for billing/quota exhaustion across providers:
#   * Moonshot: "exceeded_current_quota_error", "suspended due to insufficient balance"
#   * OpenAI: "insufficient_quota"
#   * Anthropic: "credit balance is too low"
_QUOTA_MARKERS = (
    "exceeded_current_quota_error",
    "insufficient_quota",
    "insufficient balance",
    "suspended",
    "credit balance is too low",
    "billing",
)

_AUTH_MARKERS = (
    "invalid_api_key",
    "authentication_error",
    "invalid x-api-key",
)


def classify_provider_error(exc: BaseException) -> ProviderErrorKind:
    """Best-effort classification of an LLM provider exception.

    Unrecognized errors return ``UNKNOWN`` so callers keep their existing
    generic handling.
    """
    status = getattr(exc, "status_code", None)
    text = str(exc).lower()

    if status in (401, 403) or any(m in text for m in _AUTH_MARKERS):
        return ProviderErrorKind.AUTH
    # Anthropic reports credit exhaustion as a 400, Moonshot/OpenAI as a 429;
    # the marker check keeps plain rate-limit 429s out of the quota bucket.
    if status in (400, 402, 429) and any(m in text for m in _QUOTA_MARKERS):
        return ProviderErrorKind.QUOTA
    return ProviderErrorKind.UNKNOWN
