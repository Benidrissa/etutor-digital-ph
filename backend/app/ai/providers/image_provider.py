"""Provider-agnostic image generation for lesson illustrations (#2517).

Which backend generates the text-free illustration is config-selectable via the
``ai-model-image`` platform setting and resolved by prefix. Both OpenAI's GPT
image models (:data:`OPENAI_IMAGE_MODEL`) and Google's Gemini image models are
reached through the OpenAI Images API — Gemini via its OpenAI-compatible
endpoint, reusing the same ``AsyncOpenAI`` client the vision and embeddings
services already depend on (no extra package), exactly like
``translation.vision_provider``.

Illustrations stay **text-free**; the title and labels are rendered as a DOM
overlay (#2512), so the choice of backend is purely about base-image quality.

A missing ``GOOGLE_API_KEY`` falls back to :data:`OPENAI_IMAGE_MODEL`, so a
Gemini setting never hard-fails image generation.

Story-mode art (#2675) adds two capabilities: a **transparent background** on
``generate`` (character cut-outs) and **image edit** (a character's other poses
are edits of its idle pose, so the face and outfit stay the same). Only the GPT
image models offer either through the Images API; Gemini's OpenAI-compatible
endpoint offers neither, so :func:`generate_image` and :func:`edit_image` route
those calls to :data:`OPENAI_IMAGE_MODEL` when the configured model cannot do
them, and log the routing (the ledger row then names the model actually billed).

Model churn (#2689): OpenAI shut ``gpt-image-1`` down on 2026-10-23. The
current model id lives in one constant. A configured model OpenAI no longer
knows (a 400/404 on ``param=model``) falls back to it, and is remembered for
the process. A parameter a model refuses (``background``, ``input_fidelity``,
``quality``, ``output_format``, ``size``) is dropped and the call tried once
more, and is remembered per model for the process. A transparent background so
dropped becomes a plain one-colour background in the prompt, which story art's
post-processing removes.
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, runtime_checkable

import structlog
from openai import AsyncOpenAI

from app.infrastructure.config.image_models import OPENAI_IMAGE_MODEL
from app.infrastructure.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 120.0

# OPENAI_IMAGE_MODEL (app.infrastructure.config.image_models, #2689) is the
# default, the fallback of every other backend, and the route of edits and
# transparent renders; ``ai-model-image`` can still select another.
#: The ``ai-model-image`` default.
DEFAULT_IMAGE_MODEL = OPENAI_IMAGE_MODEL
_FALLBACK_IMAGE_MODEL = OPENAI_IMAGE_MODEL

#: Image models OpenAI has shut down, mapped to their successor, so a stored
#: setting that still names one keeps working (an admin should still update
#: ``ai-model-image``). Models found missing at run time are added per process.
_RETIRED_IMAGE_MODELS: dict[str, str] = {"gpt-image-1": OPENAI_IMAGE_MODEL}

#: Parameters a model may refuse (400 ``invalid_value`` / ``unknown_parameter``
#: / ``unsupported_parameter``) that can be dropped without failing the image.
DROPPABLE_PARAMS = frozenset({"background", "input_fidelity", "quality", "output_format", "size"})
_PARAM_ERROR_CODES = frozenset({"invalid_value", "unknown_parameter", "unsupported_parameter"})
#: Per process: the parameters each model refused, never sent to it again.
_UNSUPPORTED_PARAMS: dict[str, set[str]] = {}

#: Asked for instead of a transparent background a model refuses: a background
#: the post-processing (story art's flood fill) can clear.
PLAIN_BACKGROUND = (
    " Background: one plain flat solid colour (light grey), no gradient, no texture, "
    "no shadow, no scenery, no frame."
)

#: ``background`` values the GPT image models accept; ``None`` leaves it unset
#: (the model's own default, ``auto``).
Background = Literal["transparent", "opaque", "auto"]


class ImageCapabilityError(RuntimeError):
    """The provider cannot do what was asked (an edit, a transparent background)."""


def _error_param(exc: BaseException) -> str | None:
    param = getattr(exc, "param", None)
    return param if isinstance(param, str) else None


def is_model_error(exc: BaseException | None) -> bool:
    """OpenAI does not know (or no longer offers) the requested model.

    A 400 on ``param=model`` ("does not exist", deprecated), or a 404 /
    ``model_not_found``. A configuration problem, not a property of the image.
    """
    import openai

    if not isinstance(exc, openai.APIStatusError):
        return False
    code = getattr(exc, "code", None)
    if code == "model_not_found":
        return True
    return exc.status_code in (400, 404) and _error_param(exc) == "model"


def refused_param(exc: BaseException | None) -> str | None:
    """The droppable parameter a 400 says the model does not accept, if any."""
    import openai

    if not isinstance(exc, openai.BadRequestError):
        return None
    param = _error_param(exc)
    if getattr(exc, "code", None) in _PARAM_ERROR_CODES and param in DROPPABLE_PARAMS:
        return param
    return None


def unsupported_params(model: str) -> frozenset[str]:
    """The parameters ``model`` refused in this process."""
    return frozenset(_UNSUPPORTED_PARAMS.get(model, ()))


def _remember_unsupported(model: str, param: str) -> None:
    _UNSUPPORTED_PARAMS.setdefault(model, set()).add(param)


def current_image_model(model: str | None) -> str:
    """``model``, or its successor when OpenAI has retired it."""
    requested = model or _FALLBACK_IMAGE_MODEL
    return _RETIRED_IMAGE_MODELS.get(requested, requested)


def _usage_of(response: Any) -> dict[str, int] | None:
    """The token usage a GPT image model reports, as a ledger ``usage`` dict, or None.

    ``input_tokens`` and ``output_tokens`` are what the ledger stores; the
    image/text split of the input only feeds the token pricing (image input
    is billed above the text rate, and high-fidelity edits are mostly that).
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_tokens = getattr(usage, "input_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    result = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    details = getattr(usage, "input_tokens_details", None)
    image_tokens = getattr(details, "image_tokens", None)
    text_tokens = getattr(details, "text_tokens", None)
    if isinstance(image_tokens, int) and isinstance(text_tokens, int):
        result["input_image_tokens"] = image_tokens
        result["input_text_tokens"] = text_tokens
    return result


def _client_with(client: AsyncOpenAI, *, max_retries: int | None, timeout: float | None):
    """``client``, or a copy with its own retry count and timeout for this call.

    The SDK re-sends a request on a timeout, 408/409/429 or 5xx (twice by
    default). A paid image call that runs past the timeout is often still
    completed and billed, so callers that retry on their own (story art)
    pass ``max_retries=0``. Callers that pass neither keep the client as is.
    """
    options: dict[str, Any] = {}
    if max_retries is not None:
        options["max_retries"] = max_retries
    if timeout is not None:
        options["timeout"] = timeout
    return client.with_options(**options) if options else client


@runtime_checkable
class ImageProvider(Protocol):
    """Generates (or edits) one image from a text prompt and returns the raw bytes."""

    model: str
    #: Whether ``edit`` works (image-to-image from a reference image).
    supports_edit: bool
    #: Whether ``background="transparent"`` is honoured.
    supports_transparency: bool
    #: Token usage of the last successful call, when the backend reports it.
    last_usage: dict[str, int] | None

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1536x1024",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes: ...

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes: ...


class OpenAIImageProvider:
    """OpenAI's GPT image models via the Images API."""

    supports_edit = True
    supports_transparency = True

    def __init__(self, *, api_key: str, model: str = _FALLBACK_IMAGE_MODEL) -> None:
        self._client = AsyncOpenAI(api_key=api_key, timeout=_TIMEOUT_SECONDS)
        self.model = model
        self.last_usage: dict[str, int] | None = None

    def _request(
        self, prompt: str, params: dict[str, Any], *, transparent: bool
    ) -> tuple[str, dict[str, Any]]:
        """``(prompt, params)`` without what this model refused in this process.

        A refused transparent background becomes a plain one-colour background
        in the prompt, which the post-processing can clear.
        """
        refused = unsupported_params(self.model)
        kept = {name: value for name, value in params.items() if name not in refused}
        if transparent and "background" in refused:
            prompt += PLAIN_BACKGROUND
        return prompt, kept

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1536x1024",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes:
        params: dict[str, Any] = {"size": size, "quality": "medium"}
        if background is not None:
            # A transparent background needs a format with alpha: PNG.
            params.update(background=background, output_format="png")
        prompt, params = self._request(prompt, params, transparent=background == "transparent")
        client = _client_with(self._client, max_retries=max_retries, timeout=timeout)
        response = await client.images.generate(model=self.model, prompt=prompt, **params)
        self.last_usage = _usage_of(response)
        return base64.b64decode(response.data[0].b64_json)

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes:
        """Edit ``image`` (PNG bytes) by ``prompt``; the reference keeps the identity.

        ``input_fidelity="high"`` makes the model hold the reference's features,
        faces especially, which is the point of making poses by edit. The
        ``-mini`` models do not offer it, so it is sent to the others only (and
        dropped for any model that refuses it).
        """
        params: dict[str, Any] = {"size": size, "quality": "medium"}
        if background is not None:
            params.update(background=background, output_format="png")
        if "mini" not in self.model.lower():
            params["input_fidelity"] = "high"
        prompt, params = self._request(prompt, params, transparent=background == "transparent")
        client = _client_with(self._client, max_retries=max_retries, timeout=timeout)
        response = await client.images.edit(
            model=self.model, image=("ref.png", image, "image/png"), prompt=prompt, **params
        )
        self.last_usage = _usage_of(response)
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
        self.last_usage: dict[str, int] | None = None

    async def generate(
        self,
        prompt: str,
        *,
        size: str = "1536x1024",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes:
        if background == "transparent":
            raise ImageCapabilityError(f"{self.model} cannot render a transparent background")
        # Gemini's compat endpoint controls aspect via the prompt, not a size arg;
        # request base64 so we get bytes back (not a URL) and resize downstream.
        client = _client_with(self._client, max_retries=max_retries, timeout=timeout)
        response = await client.images.generate(
            model=self.model,
            prompt=prompt,
            response_format="b64_json",
        )
        self.last_usage = _usage_of(response)
        return base64.b64decode(response.data[0].b64_json)

    async def edit(
        self,
        prompt: str,
        image: bytes,
        *,
        size: str = "1024x1536",
        background: Background | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
    ) -> bytes:
        raise ImageCapabilityError(f"{self.model} cannot edit images")


def resolve_image_provider(model: str | None = None) -> ImageProvider:
    """Build the provider that serves ``model`` (prefix dispatch).

    * ``gemini-*`` / ``imagen-*`` → Google (OpenAI-compatible endpoint), or a
      graceful fallback to :data:`OPENAI_IMAGE_MODEL` when ``GOOGLE_API_KEY``
      is unset.
    * everything else (``gpt-image-*`` / ``dall-e-*``) → OpenAI Images; a model
      OpenAI has retired resolves to its successor.
    """
    settings = get_settings()
    requested = current_image_model(model)
    if requested != (model or _FALLBACK_IMAGE_MODEL):
        logger.warning(
            "retired image model configured — using its successor",
            configured_model=model,
            model=requested,
        )
    m = requested.lower()

    if m.startswith("gemini") or m.startswith("imagen"):
        if settings.google_api_key:
            return GeminiImageProvider(
                api_key=settings.google_api_key,
                model=requested,
                base_url=settings.gemini_openai_base_url,
            )
        logger.warning(
            "GOOGLE_API_KEY unset — falling back to the OpenAI image model",
            requested_model=requested,
            model=_FALLBACK_IMAGE_MODEL,
        )
        return _openai_provider(settings, _FALLBACK_IMAGE_MODEL)

    return _openai_provider(settings, requested)


def _openai_provider(settings: Settings, model: str) -> OpenAIImageProvider:
    return OpenAIImageProvider(api_key=settings.openai_api_key, model=model)


def _image_billing_provider(model: str) -> str:
    m = model.lower()
    return "google" if m.startswith(("gemini", "imagen")) else "openai"


async def _record_attempt(
    model: str, *, error: Exception | None = None, usage: dict[str, int] | None = None
) -> None:
    """One ``ai_usage_events`` row (#2629) for one image call, failed or not.

    ``usage`` is the call's token usage when the backend reports it: the
    ledger then prices it by tokens, which counts an edit's reference image.
    """
    from app.domain.services.ai_usage_service import record_ai_usage

    if error is None:
        await record_ai_usage(
            provider=_image_billing_provider(model),
            model=model,
            operation="image",
            images_count=1,
            usage=usage,
        )
    else:
        await record_ai_usage(
            provider=_image_billing_provider(model),
            model=model,
            operation="image",
            success=False,
            error_type=type(error).__name__,
        )


async def _attempt(provider: ImageProvider, call: Callable[[ImageProvider], Awaitable[bytes]]):
    """One call on ``provider``; once more if the model refused a droppable parameter.

    Each HTTP request writes its own ledger row. The refused parameter is
    remembered for the model (this process), so later calls never send it.
    """
    try:
        image = await call(provider)
    except Exception as exc:
        await _record_attempt(provider.model, error=exc)
        param = refused_param(exc)
        if param is None or param in unsupported_params(provider.model):
            raise
        _remember_unsupported(provider.model, param)
        logger.warning(
            "image model refused a parameter — retrying without it",
            model=provider.model,
            param=param,
            error=str(exc),
        )
        try:
            image = await call(provider)
        except Exception as again:
            await _record_attempt(provider.model, error=again)
            # Another refused parameter: not retried now (one retry per call),
            # but never sent again.
            other = refused_param(again)
            if other is not None:
                _remember_unsupported(provider.model, other)
            raise
    await _record_attempt(provider.model, usage=provider.last_usage)
    return image


def _falls_back(provider: ImageProvider, exc: Exception) -> bool:
    """Whether a failure on ``provider`` is worth one try on :data:`OPENAI_IMAGE_MODEL`.

    Any failure of another backend (Gemini quota, outage). On OpenAI, only a
    model OpenAI does not know: anything else would fail the same way again.
    """
    if not isinstance(provider, OpenAIImageProvider):
        return True
    return provider.model != _FALLBACK_IMAGE_MODEL and is_model_error(exc)


async def _call_with_fallback(
    provider: ImageProvider, call: Callable[[ImageProvider], Awaitable[bytes]]
) -> tuple[bytes, str]:
    """Run ``call`` on ``provider``, falling back to :data:`OPENAI_IMAGE_MODEL` (see
    :func:`_falls_back`).

    Each attempt — including the failed primary before a fallback — writes one
    ``ai_usage_events`` row (#2629), which is what surfaces "Gemini is broken and
    we are silently paying OpenAI" on the admin cost dashboard. A model OpenAI
    does not know is remembered as retired for the process.
    """
    try:
        return await _attempt(provider, call), provider.model
    except Exception as exc:
        if not _falls_back(provider, exc):
            raise
        if is_model_error(exc):
            _RETIRED_IMAGE_MODELS[provider.model] = _FALLBACK_IMAGE_MODEL
        logger.warning(
            "image provider failed — falling back to the OpenAI image model",
            provider_model=provider.model,
            model=_FALLBACK_IMAGE_MODEL,
            error=str(exc),
        )
        fallback = _openai_provider(get_settings(), _FALLBACK_IMAGE_MODEL)
        return await _attempt(fallback, call), fallback.model


def _capable_provider(model: str, *, edit: bool, transparent: bool) -> ImageProvider:
    """The provider for ``model``, or :data:`OPENAI_IMAGE_MODEL` when it cannot do the call.

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
        "image provider lacks a capability — routing to the OpenAI image model",
        requested_model=model,
        provider_model=provider.model,
        model=_FALLBACK_IMAGE_MODEL,
        missing=missing,
    )
    return _openai_provider(get_settings(), _FALLBACK_IMAGE_MODEL)


async def generate_image(
    prompt: str,
    *,
    model: str,
    size: str = "1536x1024",
    background: Background | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> tuple[bytes, str]:
    """Generate an image for ``model``, falling back to :data:`OPENAI_IMAGE_MODEL`.

    The resolve-time fallback only covers a *missing* key. A present-but-unprivileged
    key (e.g. a free-tier Gemini key with image quota 0) raises at call time
    (429 RESOURCE_EXHAUSTED). Catch any provider error and retry once on the OpenAI
    model so image generation never hard-fails. Returns ``(image_bytes, model_used)``.

    ``background="transparent"`` (a PNG with alpha) goes straight to the OpenAI
    model when ``model`` cannot honour it (Gemini). ``max_retries``/``timeout``
    override the SDK client's for this call, the fallback's included (story
    art passes ``max_retries=0``: it retries itself, and each HTTP request
    then has its own ledger row); left unset, nothing changes.
    """
    provider = _capable_provider(model, edit=False, transparent=background == "transparent")
    return await _call_with_fallback(
        provider,
        lambda p: p.generate(
            prompt, size=size, background=background, max_retries=max_retries, timeout=timeout
        ),
    )


async def edit_image(
    prompt: str,
    image: bytes,
    *,
    model: str,
    size: str = "1024x1536",
    background: Background | None = None,
    max_retries: int | None = None,
    timeout: float | None = None,
) -> tuple[bytes, str]:
    """Edit ``image`` (PNG bytes) by ``prompt`` with ``model``; see :func:`generate_image`.

    Goes straight to the OpenAI model when ``model`` cannot edit (Gemini).
    Every attempt writes one ``ai_usage_events`` row. Returns
    ``(image_bytes, model_used)``.
    """
    provider = _capable_provider(model, edit=True, transparent=background == "transparent")
    return await _call_with_fallback(
        provider,
        lambda p: p.edit(
            prompt,
            image,
            size=size,
            background=background,
            max_retries=max_retries,
            timeout=timeout,
        ),
    )
