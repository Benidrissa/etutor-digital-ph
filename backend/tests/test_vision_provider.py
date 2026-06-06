"""Unit tests for the figure-vision provider factory (#2435)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai.translation import vision_provider as vp


def _settings(provider="gemini", anthropic="", openai="", google=""):
    s = MagicMock()
    s.figure_vision_provider = provider
    s.anthropic_api_key = anthropic
    s.openai_api_key = openai
    s.google_api_key = google
    s.figure_vision_anthropic_model = "claude-haiku-4-5"
    s.figure_vision_openai_model = "gpt-4o-mini"
    s.figure_vision_gemini_model = "gemini-2.5-flash-lite"
    s.gemini_openai_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    return s


def test_default_is_gemini_via_openai_compat():
    with patch.object(vp, "get_settings", return_value=_settings(provider="gemini", google="k")):
        provider = vp.get_vision_provider()
    assert isinstance(provider, vp.OpenAICompatVisionProvider)
    assert provider.model == "gemini-2.5-flash-lite"


def test_anthropic_provider_selected():
    with patch.object(
        vp, "get_settings", return_value=_settings(provider="anthropic", anthropic="k")
    ):
        provider = vp.get_vision_provider()
    assert isinstance(provider, vp.AnthropicVisionProvider)
    assert provider.model == "claude-haiku-4-5"


def test_openai_provider_selected():
    with patch.object(vp, "get_settings", return_value=_settings(provider="openai", openai="k")):
        provider = vp.get_vision_provider()
    assert isinstance(provider, vp.OpenAICompatVisionProvider)
    assert provider.model == "gpt-4o-mini"


def test_explicit_override_beats_config():
    with patch.object(
        vp, "get_settings", return_value=_settings(provider="gemini", anthropic="k", google="k")
    ):
        provider = vp.get_vision_provider("anthropic")
    assert isinstance(provider, vp.AnthropicVisionProvider)


def test_missing_key_raises():
    with (
        patch.object(vp, "get_settings", return_value=_settings(provider="gemini", google="")),
        pytest.raises(ValueError, match="GOOGLE_API_KEY"),
    ):
        vp.get_vision_provider()


def test_unknown_provider_raises():
    with (
        patch.object(vp, "get_settings", return_value=_settings(provider="grok")),
        pytest.raises(ValueError, match="unknown figure_vision_provider"),
    ):
        vp.get_vision_provider()
