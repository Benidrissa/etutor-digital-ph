"""Unit tests for the complex_diagram overlay renderer (issue #1883)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ai.translation.complex_overlay import (
    DiagramLabel,
    DiagramLabels,
    _escape,
    _parse_labels,
    _wrap_legend_line,
    extract_label_positions,
    render_overlay_svg,
    translate_labels,
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


class TestDiagramLabelCoercion:
    def test_accepts_percentage_0_100(self):
        label = DiagramLabel(id="n1", text="A", x_pct=42.0, y_pct=17.5)
        assert label.x_pct == 42.0 and label.y_pct == 17.5

    def test_coerces_fraction_0_1_to_percent(self):
        label = DiagramLabel(id="n1", text="A", x_pct=0.42, y_pct=0.175)
        assert label.x_pct == pytest.approx(42.0)
        assert label.y_pct == pytest.approx(17.5)

    def test_rejects_out_of_range(self):
        with pytest.raises(ValidationError):
            DiagramLabel(id="n1", text="A", x_pct=150.0, y_pct=0.0)


class TestWrapLegendLine:
    def test_short_fits_on_one_line(self):
        out = _wrap_legend_line(1, "Noyau", max_chars=40)
        assert out == ["1 — Noyau"]

    def test_long_wraps_at_words_with_indent(self):
        out = _wrap_legend_line(2, "Membrane plasmique très très longue label", max_chars=20)
        assert out[0].startswith("2 — ")
        # continuation lines are indented so the text column stays aligned
        indent = " " * len("2 — ")
        for line in out[1:]:
            assert line.startswith(indent)


class TestEscape:
    def test_escapes_xml_metachars(self):
        assert _escape("A & <B> \"c'") == "A &amp; &lt;B&gt; &quot;c&#39;"


class TestParseLabels:
    def test_strips_markdown_fences(self):
        payload = {"labels": [{"id": "n1", "text": "X", "x_pct": 10, "y_pct": 20}]}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        result = _parse_labels(fenced)
        assert result.labels[0].text == "X"

    def test_rejects_empty_labels_list(self):
        with pytest.raises(ValidationError):
            _parse_labels(json.dumps({"labels": []}))


class TestExtractLabelPositions:
    async def test_happy_path(self):
        payload = {
            "labels": [
                {"id": "n1", "text": "Nucleus", "x_pct": 42.5, "y_pct": 17.0},
                {"id": "n2", "text": "Membrane", "x_pct": 60.0, "y_pct": 50.0},
            ]
        }
        client = _mock_client(json.dumps(payload))
        result = await extract_label_positions(b"fake-webp", client=client)
        assert isinstance(result, DiagramLabels)
        assert [label.id for label in result.labels] == ["n1", "n2"]
        assert result.labels[0].x_pct == 42.5

    async def test_empty_bytes_rejected(self):
        client = _mock_client("{}")
        with pytest.raises(ValueError, match="non-empty"):
            await extract_label_positions(b"", client=client)
        client.messages.create.assert_not_awaited()

    async def test_invalid_json_raises(self):
        client = _mock_client("not json")
        with pytest.raises(ValueError):
            await extract_label_positions(b"fake-webp", client=client)

    async def test_missing_labels_fails_validation(self):
        client = _mock_client(json.dumps({}))
        with pytest.raises(ValidationError):
            await extract_label_positions(b"fake-webp", client=client)


class TestTranslateLabels:
    async def test_preserves_ids_and_coordinates(self):
        source = DiagramLabels(
            labels=[
                DiagramLabel(id="n1", text="Nucleus", x_pct=42.5, y_pct=17.0),
                DiagramLabel(id="n2", text="Membrane", x_pct=60.0, y_pct=50.0),
            ]
        )
        translated = {
            "labels": [
                {"id": "n1", "text": "Noyau", "x_pct": 42.5, "y_pct": 17.0},
                {"id": "n2", "text": "Membrane plasmique", "x_pct": 60.0, "y_pct": 50.0},
            ]
        }
        client = _mock_client(json.dumps(translated))
        out = await translate_labels(source, target_lang="fr", client=client)
        assert out.labels[0].text == "Noyau"
        assert out.labels[1].text == "Membrane plasmique"

    async def test_rejects_unsupported_target_lang(self):
        source = DiagramLabels(labels=[DiagramLabel(id="n1", text="x", x_pct=10, y_pct=10)])
        with pytest.raises(ValueError, match="unsupported target_lang"):
            await translate_labels(source, target_lang="de")

    async def test_raises_when_translator_changes_ids(self):
        source = DiagramLabels(labels=[DiagramLabel(id="n1", text="x", x_pct=10, y_pct=10)])
        rogue = {"labels": [{"id": "different", "text": "y", "x_pct": 10, "y_pct": 10}]}
        client = _mock_client(json.dumps(rogue))
        with pytest.raises(ValueError, match="changed label ids"):
            await translate_labels(source, target_lang="fr", client=client)


class TestRenderOverlaySvg:
    # We deliberately use string-based assertions instead of an XML parser
    # here — SVG 1.1 with xlink:href needs namespace awareness in ET and it's
    # more fragile than just grepping for the structural features we care
    # about.

    def test_renders_valid_svg_with_image_and_badges_and_legend(self):
        labels = DiagramLabels(
            labels=[
                DiagramLabel(id="n1", text="Noyau", x_pct=25.0, y_pct=30.0),
                DiagramLabel(id="n2", text="Membrane", x_pct=75.0, y_pct=60.0),
            ]
        )
        svg = render_overlay_svg(
            image_bytes=b"fake-webp-bytes",
            width_px=800,
            height_px=600,
            labels=labels,
        )
        body = svg.decode("utf-8")
        assert body.startswith("<svg")
        assert 'xmlns="http://www.w3.org/2000/svg"' in body
        # One embedded raster
        assert body.count("<image ") == 1
        assert 'xlink:href="data:image/webp;base64,' in body
        # One badge circle per label
        assert body.count("<circle ") == 2
        # Legend contains the translated terms
        assert "Noyau" in body
        assert "Membrane" in body

    def test_badge_positions_map_pct_to_pixels(self):
        labels = DiagramLabels(labels=[DiagramLabel(id="n1", text="X", x_pct=50.0, y_pct=25.0)])
        svg = render_overlay_svg(
            image_bytes=b"bytes",
            width_px=1000,
            height_px=400,
            labels=labels,
        ).decode("utf-8")
        # Renderer emits cx / cy rounded to 2 dp → 500.0 / 100.0.
        # Look for the exact attribute tokens.
        assert 'cx="500.0"' in svg or 'cx="500"' in svg
        assert 'cy="100.0"' in svg or 'cy="100"' in svg

    def test_xml_metachars_in_labels_escaped(self):
        labels = DiagramLabels(labels=[DiagramLabel(id="n1", text="A & <B>", x_pct=10, y_pct=10)])
        svg = render_overlay_svg(
            image_bytes=b"bytes", width_px=400, height_px=300, labels=labels
        ).decode("utf-8")
        # Raw metachars in body text would break XML; check they are escaped
        # within legend text (legend lines wrap "1 — A & <B>").
        assert "A &amp; &lt;B&gt;" in svg
        assert "A & <B>" not in svg.split("xlink:href=")[1]  # not in the svg body post-href

    def test_rejects_empty_inputs(self):
        good = DiagramLabels(labels=[DiagramLabel(id="n1", text="X", x_pct=10, y_pct=10)])
        with pytest.raises(ValueError, match="image_bytes"):
            render_overlay_svg(b"", 400, 300, good)
        with pytest.raises(ValueError, match="width_px"):
            render_overlay_svg(b"x", 0, 300, good)
        with pytest.raises(ValueError, match="labels"):
            render_overlay_svg(b"x", 400, 300, DiagramLabels.model_construct(labels=[]))

    def test_viewbox_extends_below_image_for_legend(self):
        labels = DiagramLabels(
            labels=[DiagramLabel(id=f"n{i}", text=f"L{i}", x_pct=50, y_pct=50) for i in range(5)]
        )
        svg = render_overlay_svg(
            image_bytes=b"x", width_px=600, height_px=400, labels=labels
        ).decode("utf-8")
        # Extract the viewBox value via simple string indexing.
        vb_token = 'viewBox="'
        idx = svg.index(vb_token) + len(vb_token)
        viewbox = svg[idx : svg.index('"', idx)]
        parts = viewbox.split()
        assert len(parts) == 4
        total_height = float(parts[3])
        # Image is 400 tall; 5 legend lines × 20 px line-height + padding pad
        # must push total over 400 + 5*20.
        assert total_height > 400 + 5 * 20
