"""Unit tests for ``translate_figure_caption`` (issue #1820)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ai.translation.figure_translator import (
    FigureTranslation,
    _extract_json_object,
    translate_figure_caption,
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
        body = _extract_json_object('{"caption_fr": "x"}')
        assert json.loads(body) == {"caption_fr": "x"}

    def test_strips_markdown_fences(self):
        fenced = '```json\n{"caption_fr": "x"}\n```'
        body = _extract_json_object(fenced)
        assert json.loads(body) == {"caption_fr": "x"}

    def test_strips_trailing_commas(self):
        body = _extract_json_object('{"a": 1, "b": 2,}')
        assert json.loads(body) == {"a": 1, "b": 2}

    def test_raises_when_no_object(self):
        with pytest.raises(ValueError, match="no JSON object"):
            _extract_json_object("Sorry, I cannot comply.")


class TestTranslateFigureCaption:
    async def test_happy_path_returns_all_four_fields(self):
        payload = {
            "caption_fr": "Le cycle épidémiologique",
            "caption_en": "The epidemiological cycle",
            "alt_text_fr": "Schéma montrant les étapes du cycle épidémiologique",
            "alt_text_en": "Diagram showing the steps of the epidemiological cycle",
        }
        client = _mock_client(json.dumps(payload))
        result = await translate_figure_caption(
            caption="Le cycle épidémiologique",
            image_type="diagram",
            figure_number="2.5",
            client=client,
        )
        assert isinstance(result, FigureTranslation)
        assert result.caption_fr == payload["caption_fr"]
        assert result.caption_en == payload["caption_en"]
        assert result.alt_text_fr == payload["alt_text_fr"]
        assert result.alt_text_en == payload["alt_text_en"]

    async def test_markdown_fenced_response_is_parsed(self):
        payload = {
            "caption_fr": "Diagramme",
            "caption_en": "Diagram",
            "alt_text_fr": "Un diagramme",
            "alt_text_en": "A diagram",
        }
        fenced = f"```json\n{json.dumps(payload)}\n```"
        client = _mock_client(fenced)
        result = await translate_figure_caption(caption="Diagram", client=client)
        assert result.caption_fr == "Diagramme"

    async def test_empty_caption_rejected_before_api_call(self):
        client = _mock_client("{}")
        with pytest.raises(ValueError, match="non-empty"):
            await translate_figure_caption(caption="   ", client=client)
        client.messages.create.assert_not_awaited()

    async def test_invalid_json_raises_value_error(self):
        client = _mock_client("This is not JSON at all.")
        with pytest.raises(ValueError):
            await translate_figure_caption(caption="X", client=client)

    async def test_missing_field_raises_validation_error(self):
        payload = {
            "caption_fr": "A",
            "caption_en": "B",
            "alt_text_fr": "C",
            # alt_text_en missing
        }
        client = _mock_client(json.dumps(payload))
        with pytest.raises(ValidationError):
            await translate_figure_caption(caption="X", client=client)

    async def test_empty_text_response_raises(self):
        client = _mock_client("")
        with pytest.raises(ValueError, match="empty translator response"):
            await translate_figure_caption(caption="X", client=client)

    async def test_caption_image_type_and_figure_number_in_prompt(self):
        payload = {
            "caption_fr": "a",
            "caption_en": "b",
            "alt_text_fr": "c",
            "alt_text_en": "d",
        }
        client = _mock_client(json.dumps(payload))
        await translate_figure_caption(
            caption="Marketing funnel",
            image_type="chart",
            figure_number="1.3",
            client=client,
        )
        call = client.messages.create.await_args
        user_msg = call.kwargs["messages"][0]["content"]
        assert "Marketing funnel" in user_msg
        assert "chart" in user_msg
        assert "1.3" in user_msg
