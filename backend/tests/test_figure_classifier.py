"""Unit tests for ``classify_figure`` (issue #1844)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.ai.translation import figure_classifier
from app.ai.translation.figure_classifier import (
    FigureClassification,
    _extract_json_object,
    classify_figure,
)


def _mock_anthropic_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = [SimpleNamespace(text=text)]
    return msg


def _mock_client(text: str) -> MagicMock:
    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=_mock_anthropic_response(text))
    return client


class TestExtractJsonObject:
    def test_plain_json_passes_through(self):
        body = _extract_json_object('{"kind": "chart"}')
        assert json.loads(body) == {"kind": "chart"}

    def test_strips_markdown_fences(self):
        body = _extract_json_object('```json\n{"kind": "photo"}\n```')
        assert json.loads(body) == {"kind": "photo"}

    def test_raises_when_no_object(self):
        with pytest.raises(ValueError, match="no JSON object"):
            _extract_json_object("Sorry, I cannot classify this image.")


class TestClassifyFigure:
    async def test_happy_path_returns_valid_kind(self):
        client = _mock_client(json.dumps({"kind": "clean_flowchart"}))
        result = await classify_figure(image_bytes=b"fake-webp", client=client)
        assert isinstance(result, FigureClassification)
        assert result.kind == "clean_flowchart"

    async def test_raises_when_vision_disabled(self):
        # Cost kill-switch (#1928) — even with a mock client supplied, the
        # function must refuse to make the Vision call when the flag is off.
        client = _mock_client(json.dumps({"kind": "photo"}))
        fake_settings = MagicMock(enable_figure_vision=False, anthropic_api_key="key")
        with (
            patch.object(figure_classifier, "get_settings", return_value=fake_settings),
            pytest.raises(RuntimeError, match="vision is disabled"),
        ):
            await classify_figure(image_bytes=b"fake-webp", client=client)
        client.messages.create.assert_not_awaited()

    @pytest.mark.parametrize(
        "kind",
        [
            "clean_flowchart",
            "chart",
            "table",
            "photo",
            "photo_with_callouts",
            "formula",
            "micrograph",
            "decorative",
            "complex_diagram",
        ],
    )
    async def test_each_allowed_kind_parses(self, kind: str):
        client = _mock_client(json.dumps({"kind": kind}))
        result = await classify_figure(image_bytes=b"fake-webp", client=client)
        assert result.kind == kind

    async def test_markdown_fenced_response_is_parsed(self):
        fenced = '```json\n{"kind": "table"}\n```'
        client = _mock_client(fenced)
        result = await classify_figure(image_bytes=b"fake-webp", client=client)
        assert result.kind == "table"

    async def test_empty_bytes_rejected_before_api_call(self):
        client = _mock_client('{"kind": "photo"}')
        with pytest.raises(ValueError, match="non-empty"):
            await classify_figure(image_bytes=b"", client=client)
        client.messages.create.assert_not_awaited()

    async def test_unknown_kind_rejected(self):
        client = _mock_client(json.dumps({"kind": "screenshot_of_tweet"}))
        with pytest.raises(ValueError, match="unknown kind"):
            await classify_figure(image_bytes=b"fake-webp", client=client)

    async def test_invalid_json_raises_value_error(self):
        client = _mock_client("Not JSON at all")
        with pytest.raises(ValueError):
            await classify_figure(image_bytes=b"fake-webp", client=client)

    async def test_missing_kind_field_raises_validation_error(self):
        client = _mock_client(json.dumps({"confidence": 0.9}))
        with pytest.raises(ValidationError):
            await classify_figure(image_bytes=b"fake-webp", client=client)

    async def test_empty_text_response_raises(self):
        client = _mock_client("")
        with pytest.raises(ValueError, match="empty classifier response"):
            await classify_figure(image_bytes=b"fake-webp", client=client)

    async def test_image_bytes_sent_as_base64_in_vision_payload(self):
        client = _mock_client(json.dumps({"kind": "photo"}))
        await classify_figure(
            image_bytes=b"hello-world-bytes",
            image_media_type="image/png",
            client=client,
        )
        call = client.messages.create.await_args
        user_content = call.kwargs["messages"][0]["content"]
        # First block is the image, second is text.
        image_block = user_content[0]
        assert image_block["type"] == "image"
        assert image_block["source"]["media_type"] == "image/png"
        # base64 of b"hello-world-bytes"
        import base64

        assert image_block["source"]["data"] == base64.standard_b64encode(
            b"hello-world-bytes"
        ).decode("ascii")
