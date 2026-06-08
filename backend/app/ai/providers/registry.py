"""Model → provider resolution (#2443).

Mirrors ``vision_provider.get_vision_provider``: maps a model string to a built
provider, raising a clear error when the required API key is unset. Prefix-based
dispatch keeps it open for new OpenAI-compatible backends without touching call
sites — only the registry and a settings key change.
"""

from __future__ import annotations

from app.ai.providers.anthropic_provider import AnthropicLLMProvider
from app.ai.providers.base import LLMProvider
from app.ai.providers.openai_compat_provider import OpenAICompatLLMProvider
from app.infrastructure.config.settings import get_settings


def resolve_provider(model: str) -> LLMProvider:
    """Build the provider that serves ``model``.

    Dispatch:
      * ``claude-*`` / ``anthropic-*`` → Anthropic
      * ``kimi-*`` / ``moonshot-*``    → Moonshot (OpenAI-compatible)
      * ``gpt-*``                      → OpenAI
      * contains ``/`` (e.g. ``moonshotai/kimi-k2.6``) → OpenRouter
    """
    settings = get_settings()
    m = (model or "").lower()

    if m.startswith("claude") or m.startswith("anthropic"):
        if not settings.anthropic_api_key:
            raise ValueError(f"ANTHROPIC_API_KEY required for model {model!r}")
        return AnthropicLLMProvider(api_key=settings.anthropic_api_key)

    if m.startswith("kimi") or m.startswith("moonshot"):
        if not settings.moonshot_api_key:
            raise ValueError(f"MOONSHOT_API_KEY required for model {model!r}")
        return OpenAICompatLLMProvider(
            api_key=settings.moonshot_api_key,
            base_url=settings.moonshot_base_url,
        )

    if m.startswith("gpt") or m.startswith("openai"):
        if not settings.openai_api_key:
            raise ValueError(f"OPENAI_API_KEY required for model {model!r}")
        return OpenAICompatLLMProvider(api_key=settings.openai_api_key)

    if "/" in m:  # OpenRouter-style "vendor/model"
        if not settings.openrouter_api_key:
            raise ValueError(f"OPENROUTER_API_KEY required for model {model!r}")
        return OpenAICompatLLMProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )

    raise ValueError(f"No provider mapping for model {model!r}")
