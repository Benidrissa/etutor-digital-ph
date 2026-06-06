"""Unit tests for read_figure_caption (#2435)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ai.translation import figure_caption_reader as fcr
from app.ai.translation.figure_caption_reader import read_figure_caption


class _FakeProvider:
    def __init__(self, text: str):
        self._text = text
        self.model = "fake"

    async def complete_json(self, **kwargs) -> str:
        return self._text


def _enabled():
    return MagicMock(enable_figure_vision=True)


@pytest.mark.asyncio
async def test_reads_real_caption():
    provider = _FakeProvider(
        json.dumps(
            {"caption": "The Learning Curve and the Cost of Production", "is_body_text": False}
        )
    )
    with patch.object(fcr, "get_settings", return_value=_enabled()):
        result = await read_figure_caption(b"webp", provider=provider)
    assert result.caption == "The Learning Curve and the Cost of Production"
    assert result.is_body_text is False


@pytest.mark.asyncio
async def test_body_text_flagged_with_null_caption():
    provider = _FakeProvider(json.dumps({"caption": None, "is_body_text": True}))
    with patch.object(fcr, "get_settings", return_value=_enabled()):
        result = await read_figure_caption(b"webp", provider=provider)
    assert result.is_body_text is True
    assert result.caption is None


@pytest.mark.asyncio
async def test_blank_caption_normalised_to_none():
    provider = _FakeProvider(json.dumps({"caption": "   ", "is_body_text": False}))
    with patch.object(fcr, "get_settings", return_value=_enabled()):
        result = await read_figure_caption(b"webp", provider=provider)
    assert result.caption is None


@pytest.mark.asyncio
async def test_markdown_fenced_json_parsed():
    provider = _FakeProvider('```json\n{"caption": "A bar chart", "is_body_text": false}\n```')
    with patch.object(fcr, "get_settings", return_value=_enabled()):
        result = await read_figure_caption(b"webp", provider=provider)
    assert result.caption == "A bar chart"


@pytest.mark.asyncio
async def test_disabled_raises():
    with (
        patch.object(fcr, "get_settings", return_value=MagicMock(enable_figure_vision=False)),
        pytest.raises(RuntimeError, match="disabled"),
    ):
        await read_figure_caption(b"webp", provider=_FakeProvider("{}"))


@pytest.mark.asyncio
async def test_empty_bytes_raises():
    with pytest.raises(ValueError, match="non-empty"):
        await read_figure_caption(b"", provider=_FakeProvider("{}"))


@pytest.mark.asyncio
async def test_invalid_json_raises():
    with patch.object(fcr, "get_settings", return_value=_enabled()), pytest.raises(ValueError):
        await read_figure_caption(b"webp", provider=_FakeProvider("not json at all"))
