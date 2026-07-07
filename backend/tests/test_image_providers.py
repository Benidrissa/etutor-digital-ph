"""Tests for the pluggable image-generation providers (#2517)."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.providers.image_provider import (
    GeminiImageProvider,
    OpenAIImageProvider,
    generate_image,
    resolve_image_provider,
)

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _settings(*, google: str = "", openai: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        google_api_key=google,
        openai_api_key=openai,
        gemini_openai_base_url=_GEMINI_BASE_URL,
    )


def _fake_image_response(payload: bytes = b"IMG") -> MagicMock:
    response = MagicMock()
    response.data = [MagicMock(b64_json=base64.b64encode(payload).decode())]
    return response


class TestResolveImageProvider:
    def test_gemini_model_resolves_to_gemini_when_google_key_present(self):
        with patch(
            "app.ai.providers.image_provider.get_settings",
            return_value=_settings(google="gk", openai="ok"),
        ):
            provider = resolve_image_provider("gemini-2.5-flash-image")
        assert isinstance(provider, GeminiImageProvider)
        assert provider.model == "gemini-2.5-flash-image"

    def test_imagen_model_resolves_to_gemini(self):
        with patch(
            "app.ai.providers.image_provider.get_settings",
            return_value=_settings(google="gk", openai="ok"),
        ):
            provider = resolve_image_provider("imagen-4.0-generate-001")
        assert isinstance(provider, GeminiImageProvider)

    def test_gemini_falls_back_to_openai_when_google_key_missing(self):
        with patch(
            "app.ai.providers.image_provider.get_settings",
            return_value=_settings(google="", openai="ok"),
        ):
            provider = resolve_image_provider("gemini-2.5-flash-image")
        assert isinstance(provider, OpenAIImageProvider)
        assert provider.model == "gpt-image-1"

    def test_gpt_image_resolves_to_openai(self):
        with patch(
            "app.ai.providers.image_provider.get_settings",
            return_value=_settings(openai="ok"),
        ):
            provider = resolve_image_provider("gpt-image-1")
        assert isinstance(provider, OpenAIImageProvider)
        assert provider.model == "gpt-image-1"

    def test_none_defaults_to_openai_backend(self):
        with patch(
            "app.ai.providers.image_provider.get_settings",
            return_value=_settings(openai="ok"),
        ):
            provider = resolve_image_provider(None)
        assert isinstance(provider, OpenAIImageProvider)


class TestOpenAIImageProvider:
    async def test_generate_calls_images_api_with_quality_and_size(self):
        with patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_cls:
            client = MagicMock()
            client.images.generate = AsyncMock(return_value=_fake_image_response(b"PNG"))
            mock_cls.return_value = client

            provider = OpenAIImageProvider(api_key="ok")
            out = await provider.generate("a prompt", size="1536x1024")

            kwargs = client.images.generate.call_args.kwargs
            assert kwargs["model"] == "gpt-image-1"
            assert kwargs["size"] == "1536x1024"
            assert kwargs["quality"] == "medium"
            assert out == b"PNG"


class TestGeminiImageProvider:
    async def test_generate_uses_base_url_and_b64_response_format(self):
        with patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_cls:
            client = MagicMock()
            client.images.generate = AsyncMock(return_value=_fake_image_response(b"GEM"))
            mock_cls.return_value = client

            provider = GeminiImageProvider(
                api_key="gk",
                model="gemini-2.5-flash-image",
                base_url=_GEMINI_BASE_URL,
            )
            out = await provider.generate("a prompt")

            # Client built against Google's OpenAI-compatible endpoint.
            assert mock_cls.call_args.kwargs["base_url"] == _GEMINI_BASE_URL
            assert mock_cls.call_args.kwargs["api_key"] == "gk"
            kwargs = client.images.generate.call_args.kwargs
            assert kwargs["model"] == "gemini-2.5-flash-image"
            assert kwargs["response_format"] == "b64_json"
            assert out == b"GEM"


@pytest.mark.parametrize("model", ["gemini-2.5-flash-image", "gpt-image-1"])
def test_default_setting_options_resolve(model):
    """Both allowed_options for ai-model-image must resolve to a provider."""
    with patch(
        "app.ai.providers.image_provider.get_settings",
        return_value=_settings(google="gk", openai="ok"),
    ):
        assert resolve_image_provider(model) is not None


class TestGenerateImageFallback:
    async def test_success_returns_model_used(self):
        with (
            patch(
                "app.ai.providers.image_provider.get_settings",
                return_value=_settings(openai="ok"),
            ),
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_cls,
        ):
            client = MagicMock()
            client.images.generate = AsyncMock(return_value=_fake_image_response(b"OK"))
            mock_cls.return_value = client

            data, used = await generate_image("p", model="gpt-image-1")
            assert data == b"OK"
            assert used == "gpt-image-1"

    async def test_falls_back_to_openai_when_gemini_errors(self):
        """A runtime Gemini error (e.g. 429 quota) must fall back to gpt-image-1."""
        with (
            patch(
                "app.ai.providers.image_provider.get_settings",
                return_value=_settings(google="gk", openai="ok"),
            ),
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_cls,
        ):
            client = MagicMock()
            # First call (Gemini) raises; second call (gpt-image-1 fallback) succeeds.
            client.images.generate = AsyncMock(
                side_effect=[RuntimeError("429 RESOURCE_EXHAUSTED"), _fake_image_response(b"FB")]
            )
            mock_cls.return_value = client

            data, used = await generate_image("p", model="gemini-2.5-flash-image")
            assert data == b"FB"
            assert used == "gpt-image-1"
            assert client.images.generate.await_count == 2

    async def test_no_double_fallback_when_openai_itself_errors(self):
        """If the backend is already gpt-image-1, an error must propagate (no loop)."""
        with (
            patch(
                "app.ai.providers.image_provider.get_settings",
                return_value=_settings(openai="ok"),
            ),
            patch("app.ai.providers.image_provider.AsyncOpenAI") as mock_cls,
        ):
            client = MagicMock()
            client.images.generate = AsyncMock(side_effect=RuntimeError("openai down"))
            mock_cls.return_value = client

            with pytest.raises(RuntimeError):
                await generate_image("p", model="gpt-image-1")
            assert client.images.generate.await_count == 1
