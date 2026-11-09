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

Story-mode art (#2675) adds two capabilities: a **transparent background** on
``generate`` (character cut-outs) and **image edit** (a character's other poses
are edits of its idle pose, so the face and outfit stay the same). Only the GPT
image models offer either through the Images API; Gemini's OpenAI-compatible
endpoint offers neither, so :func:`generate_image` and :func:`edit_image` route
those calls to ``gpt-image-1`` when the configured model cannot do them, and log
the routing (the ledger row then names the model actually billed).
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, runtime_checkable

import structlog
from openai import AsyncOpenAI

from app.infrastructure.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 120.0

# Default backend. Gemini ("Nano Banana") gives stronger prompt adherence and
# base-image quality than gpt-image-1.
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"
_FALLBACK_IMAGE_MODEL = "gpt-image-1"

#: ``background`` values the GPT image models accept; ``None`` leaves it unset
#: (the model's own default, ``auto``).
Background = Literal["transparent", "opaque", "auto"]


class ImageCapabilityError(RuntimeError):
    """The provider cannot do what was asked (an edit, a transparent background)."""


@runtime_checkable
class ImageProvider(Protocol):
    """Generates (or edits) one image from a text prompt and returns the raw bytes."""

    model: str
    #: Whether ``edit`` works (image-to-image from a reference image).
    supports_edit: bool
    #: Whether ``background="transparent"`` is honoured.
    supports_transparency: bool

    async def generate(
        self, prompt: str, *, size: str = "1536x1024", background: Background | None = None
    ) -> bytes: ...

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
    ) -> bytes: ...


class OpenAIImageProvider:
    """gpt-image-1 via the OpenAI Images API."""

    supports_edit = True
    supports_transparency = True

    def __init__(self, *, api_key: str, model: str = _FALLBACK_IMAGE_MODEL) -> None:
        self._client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def generate(
        self, prompt: str, *, size: str = "1536x1024", background: Background | None = None
    ) -> bytes:
        extra: dict = {}
        if background is not None:
            # A transparent background needs a format with alpha: PNG.
            extra = {"background": background, "output_format": "png"}
        response = await self._client.images.generate(
            model=self.model,
            prompt=prompt,
            size=size,
            quality="medium",
            **extra,
        )
        return base64.b64decode(response.data[0].b64_json)

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
    ) -> bytes:
        """Edit ``image`` (PNG bytes) by ``prompt``; the reference keeps the identity.

        ``input_fidelity="high"`` makes the model hold the reference's features,
        faces especially, which is the point of making poses by edit. The
        ``-mini`` models do not offer it, so it is sent to the others only.
        """
        extra: dict = {}
        if background is not None:
            extra = {"background": background, "output_format": "png"}
        if "mini" not in self.model.lower():
            extra["input_fidelity"] = "high"
        response = await self._client.images.edit(
            model=self.model,
            image=("ref.png", image, "image/png"),
            prompt=prompt,
            size=size,
            quality="medium",
            **extra,
        )
        return base64.b64decode(response.data[0].b64_json)


class GeminiImageProvider:
    """Gemini image models via Google's OpenAI-compatible Images endpoint.

    The compat endpoint generates only: no edit, no transparent background.
    """

    supports_edit = False
    supports_transparency = False

    def __init__(self, *, api_key: str, model: str, base_url: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=_TIMEOUT_SECONDS)
        self.model = model

    async def generate(
        self, prompt: str, *, size: str = "1536x1024", background: Background | None = None
    ) -> bytes:
        if background == "transparent":
            raise ImageCapabilityError(f"{self.model} cannot render a transparent background")
        # Gemini's compat endpoint controls aspect via the prompt, not a size arg;
        # request base64 so we get bytes back (not a URL) and resize downstream.
        response = await self._client.images.generate(
            model=self.model,
            prompt=prompt,
            response_format="b64_json",
        )
        return base64.b64decode(response.data[0].b64_json)

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
    ) -> bytes:
        raise ImageCapabilityError(f"{self.model} cannot edit images")


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


def _image_billing_provider(model: str) -> str:
    m = model.lower()
    return "google" if m.startswith(("gemini", "imagen")) else "openai"


async def _record_attempt(model: str, *, error: Exception | None = None) -> None:
    """One ``ai_usage_events`` row (#2629) for one image call, failed or not."""
    from app.domain.services.ai_usage_service import record_ai_usage

    if error is None:
        await record_ai_usage(
            provider=_image_billing_provider(model),
            model=model,
            operation="image",
            images_count=1,
        )
    else:
        await record_ai_usage(
            provider=_image_billing_provider(model),
            model=model,
            operation="image",
            success=False,
            error_type=type(error).__name__,
        )


async def _call_with_fallback(
    provider: ImageProvider, call: Callable[[ImageProvider], Awaitable[bytes]]
) -> tuple[bytes, str]:
    """Run ``call`` on ``provider``, falling back to gpt-image-1 on any error.

    Each attempt — including the failed primary before a fallback — writes one
    ``ai_usage_events`` row (#2629), which is what surfaces "Gemini is broken and
    we are silently paying gpt-image-1" on the admin cost dashboard.
    """
    try:
        image = await call(provider)
    except Exception as exc:
        await _record_attempt(provider.model, error=exc)
        if isinstance(provider, OpenAIImageProvider):
            raise  # already on the fallback backend — nothing left to try
        logger.warning(
            "image provider failed — falling back to gpt-image-1",
            provider_model=provider.model,
            error=str(exc),
        )
        fallback = _openai_provider(get_settings(), _FALLBACK_IMAGE_MODEL)
        try:
            image = await call(fallback)
        except Exception as fallback_exc:
            await _record_attempt(fallback.model, error=fallback_exc)
            raise
        await _record_attempt(fallback.model)
        return image, fallback.model
    await _record_attempt(provider.model)
    return image, provider.model


def _capable_provider(model: str, *, edit: bool, transparent: bool) -> ImageProvider:
    """The provider for ``model``, or gpt-image-1 when ``model`` cannot do the call.

    A capability routing is not a failure, so it writes no ledger row of its
    own: it is logged, and the call's ledger row names the model billed.
    """
    provider = resolve_image_provider(model)
    missing = [
        name
        for name, needed, has in (
            ("edit", edit, provider.supports_edit),
            ("transparency", transparent, provider.supports_transparency),
        )
        if needed and not has
    ]
    if not missing:
        return provider
    logger.info(
        "image provider lacks a capability — routing to gpt-image-1",
        requested_model=model,
        provider_model=provider.model,
        missing=missing,
    )
    return _openai_provider(get_settings(), _FALLBACK_IMAGE_MODEL)


async def generate_image(
    prompt: str,
    *,
    model: str,
    size: str = "1536x1024",
    background: Background | None = None,
) -> tuple[bytes, str]:
    """Generate an image for ``model``, falling back to gpt-image-1 on any error.

    The resolve-time fallback only covers a *missing* key. A present-but-unprivileged
    key (e.g. a free-tier Gemini key with image quota 0) raises at call time
    (429 RESOURCE_EXHAUSTED). Catch any provider error and retry once on gpt-image-1
    so image generation never hard-fails. Returns ``(image_bytes, model_used)``.

    ``background="transparent"`` (a PNG with alpha) goes straight to gpt-image-1
    when ``model`` cannot honour it (Gemini).
    """
    provider = _capable_provider(model, edit=False, transparent=background == "transparent")
    return await _call_with_fallback(
        provider, lambda p: p.generate(prompt, size=size, background=background)
    )


async def edit_image(
    prompt: str,
    image: bytes,
    *,
    model: str,
    size: str = "1024x1536",
    background: Background | None = None,
) -> tuple[bytes, str]:
    """Edit ``image`` (PNG bytes) by ``prompt`` with ``model``; see :func:`generate_image`.

    Goes straight to gpt-image-1 when ``model`` cannot edit (Gemini), and falls
    back to it on any error. Every attempt writes one ``ai_usage_events`` row.
    Returns ``(image_bytes, model_used)``.
    """
    provider = _capable_provider(model, edit=True, transparent=background == "transparent")
    return await _call_with_fallback(
        provider, lambda p: p.edit(prompt, image, size=size, background=background)
    )
