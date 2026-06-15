"""Provider-agnostic image generation for lesson illustrations (#2517).

Which backend generates the text-free illustration is config-selectable via the
``ai-model-image`` platform setting and resolved by prefix. Both OpenAI
(``gpt-image-1``) and Google's Gemini image models are reached through the OpenAI
Images API — Gemini via its OpenAI-compatible endpoint, reusing the same
``AsyncOpenAI`` client the vision and embeddings services already depend on (no
extra package), exactly like ``translation.vision_provider``.

Illustrations stay **text-free**; the title and labels are rendered as a DOM
overlay (#2512), so the choice of backend is purely about base-image quality.

A missing ``GOOGLE_API_KEY`` transparently falls back to ``gpt-image-1`` so a
Gemini default never hard-fails image generation.
"""

from __future__ import annotations

import base64
from typing import Protocol, runtime_checkable

import structlog
from openai import AsyncOpenAI

from app.infrastructure.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 120.0

# Default backend. Gemini ("Nano Banana") gives stronger prompt adherence and
# base-image quality than gpt-image-1.
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
_FALLBACK_IMAGE_MODEL = "gpt-image-1"


@runtime_checkable
class ImageProvider(Protocol):
    """Generates one image from a text prompt and returns the raw bytes."""

    model: str

    async def generate(self, prompt: str, *, size: str = "1536x1024") -> bytes: ...


class OpenAIImageProvider:
    """gpt-image-1 via the OpenAI Images API."""

    def __init__(self, *, api_key: str, model: str = _FALLBACK_IMAGE_MODEL) -> None:
        self._client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def generate(self, prompt: str, *, size: str = "1536x1024") -> bytes:
        response = await self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size=size,
            quality="medium",
        )
        return base64.b64decode(response.data[0].b64_json)


class GeminiImageProvider:
    """Gemini image models via Google's OpenAI-compatible Images endpoint."""

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def generate(self, prompt: str, *, size: str = "1536x1024") -> bytes:
        # Gemini's compat endpoint controls aspect via the prompt, not a size arg;
        # request base64 so we get bytes back (not a URL) and resize downstream.
        response = await self._client.images.generate(
            model=self.model,
            prompt=prompt,
            response_format="b64_json",
        )
        return base64.b64decode(response.data[0].b64_json)


def resolve_image_provider(model: str | None = None) -> ImageProvider:
    """Build the provider that serves ``model`` (prefix dispatch).

    * ``gemini-*`` / ``imagen-*`` → Google (OpenAI-compatible endpoint), or a
      graceful fallback to ``gpt-image-1`` when ``GOOGLE_API_KEY`` is unset.
    * everything else (``gpt-image-*`` / ``dall-e-*``) → OpenAI Images.
    """
    settings = get_settings()
    requested = model or _FALLBACK_IMAGE_MODEL
    m = requested.lower()

    if m.startswith("gemini") or m.startswith("imagen"):
        if settings.google_api_key:
            return GeminiImageProvider(
                api_key=settings.google_api_key,
                model=requested,
                base_url=settings.gemini_openai_base_url,
            )
        logger.warning(
            "GOOGLE_API_KEY unset — falling back to gpt-image-1 for image generation",
            requested_model=requested,
        )
        return _openai_provider(settings, _FALLBACK_IMAGE_MODEL)

    return _openai_provider(settings, requested)


def _openai_provider(settings: Settings, model: str) -> OpenAIImageProvider:
    return OpenAIImageProvider(api_key=settings.openai_api_key, model=model)
