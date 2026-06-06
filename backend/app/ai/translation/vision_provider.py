"""Provider-agnostic vision interface for figure tasks (#2435).

The figure classifier and caption reader send one image + a JSON-only prompt to
a vision model. Which model runs is config-selectable
(``settings.figure_vision_provider``) so we can use the cheapest accurate VLM —
Gemini 2.5 Flash-Lite (~$0.10/$0.40 per 1M; a figure image bills ~258 tokens) —
without locking the codebase to one vendor.

Gemini is reached through its OpenAI-compatible endpoint, so it reuses the same
``AsyncOpenAI`` client the embeddings service already depends on — no extra
package. ``anthropic`` (Haiku) and ``openai`` (GPT-4o-mini) remain available by
flipping one setting.
"""

from __future__ import annotations

import base64
from typing import Protocol, runtime_checkable

import anthropic
import structlog
from openai import AsyncOpenAI

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 60.0


@runtime_checkable
class VisionProvider(Protocol):
    """Sends one image + a JSON-only prompt and returns the raw text response."""

    model: str

    async def complete_json(
        self,
        *,
        image_bytes: bytes,
        image_media_type: str,
        system: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str: ...


class AnthropicVisionProvider:
    """Claude vision via the Anthropic Messages API."""

    def __init__(self, *, api_key: str, model: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def complete_json(
        self,
        *,
        image_bytes: bytes,
        image_media_type: str,
        system: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_media_type,
                                "data": encoded,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                }
            ],
            temperature=0.0,
        )
        return "".join(block.text for block in response.content if hasattr(block, "text"))


class OpenAICompatVisionProvider:
    """OpenAI Chat Completions vision — also serves Gemini via its
    OpenAI-compatible endpoint (different ``base_url`` + key + model)."""

    def __init__(self, *, api_key: str, model: str, base_url: str | None = None) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def complete_json(
        self,
        *,
        image_bytes: bytes,
        image_media_type: str,
        system: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        data_uri = f"data:{image_media_type};base64,{encoded}"
        response = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_uri}},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            temperature=0.0,
        )
        return response.choices[0].message.content or ""


def get_vision_provider(provider: str | None = None) -> VisionProvider:
    """Build the configured vision provider. Raises if its key is missing."""
    settings = get_settings()
    provider = provider or settings.figure_vision_provider

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY required for figure_vision_provider=anthropic")
        return AnthropicVisionProvider(
            api_key=settings.anthropic_api_key,
            model=settings.figure_vision_anthropic_model,
        )
    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY required for figure_vision_provider=openai")
        return OpenAICompatVisionProvider(
            api_key=settings.openai_api_key,
            model=settings.figure_vision_openai_model,
        )
    if provider == "gemini":
        if not settings.google_api_key:
            raise ValueError("GOOGLE_API_KEY required for figure_vision_provider=gemini")
        return OpenAICompatVisionProvider(
            api_key=settings.google_api_key,
            model=settings.figure_vision_gemini_model,
            base_url=settings.gemini_openai_base_url,
        )
    raise ValueError(f"unknown figure_vision_provider: {provider!r}")
