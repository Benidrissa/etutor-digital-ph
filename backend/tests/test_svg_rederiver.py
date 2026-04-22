"""Unit tests for the flowchart SVG re-deriver (issue #1852)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.ai.translation.svg_rederiver import (
    FlowchartEdge,
    FlowchartNode,
    FlowchartStructure,
    _assign_layers,
    _escape,
    _wrap,
    extract_flowchart_structure,
    render_svg,
    translate_structure,
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


# ---------------------------------------------------------------------------
# Parsing / layout helpers
# ---------------------------------------------------------------------------


class TestWrap:
    def test_short_text_single_line(self):
        assert _wrap("Hello") == ["Hello"]

    def test_wraps_on_spaces(self):
        lines = _wrap("This is a rather long sentence that should wrap", max_chars=12)
        assert all(len(line) <= 12 for line in lines)
        assert " ".join(lines) == "This is a rather long sentence that should wrap"

    def test_explicit_newlines_preserved(self):
        assert _wrap("line1\nline2") == ["line1", "line2"]


class TestEscape:
    def test_escapes_xml_metachars(self):
        assert _escape("A & <B> \"quote'") == "A &amp; &lt;B&gt; &quot;quote&#39;"


class TestAssignLayers:
    def test_linear_chain_produces_sequential_layers(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="a", text="A"),
                FlowchartNode(id="b", text="B"),
                FlowchartNode(id="c", text="C"),
            ],
            edges=[
                FlowchartEdge(from_id="a", to_id="b"),
                FlowchartEdge(from_id="b", to_id="c"),
            ],
        )
        layers = _assign_layers(structure)
        assert layers == {"a": 0, "b": 1, "c": 2}

    def test_branching_same_layer(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="root", text="root"),
                FlowchartNode(id="left", text="left"),
                FlowchartNode(id="right", text="right"),
            ],
            edges=[
                FlowchartEdge(from_id="root", to_id="left"),
                FlowchartEdge(from_id="root", to_id="right"),
            ],
        )
        layers = _assign_layers(structure)
        assert layers["root"] == 0
        assert layers["left"] == 1
        assert layers["right"] == 1

    def test_cycle_does_not_loop_forever(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="a", text="A"),
                FlowchartNode(id="b", text="B"),
            ],
            edges=[
                FlowchartEdge(from_id="a", to_id="b"),
                FlowchartEdge(from_id="b", to_id="a"),
            ],
        )
        layers = _assign_layers(structure)
        assert set(layers.keys()) == {"a", "b"}


# ---------------------------------------------------------------------------
# Structure extraction (Claude Vision mocked)
# ---------------------------------------------------------------------------


class TestExtractFlowchartStructure:
    async def test_happy_path_parses_structure(self):
        payload = {
            "nodes": [
                {"id": "n1", "text": "Make an observation", "shape": "rect"},
                {"id": "n2", "text": "Ask a question", "shape": "rect"},
            ],
            "edges": [{"from_id": "n1", "to_id": "n2"}],
        }
        client = _mock_client(json.dumps(payload))
        result = await extract_flowchart_structure(b"fake-webp", client=client)
        assert isinstance(result, FlowchartStructure)
        assert result.nodes[0].text == "Make an observation"
        assert result.edges[0].from_id == "n1"
        assert result.edges[0].label is None

    async def test_strips_markdown_fences(self):
        payload = {
            "nodes": [{"id": "n1", "text": "Start"}],
            "edges": [],
        }
        fenced = f"```json\n{json.dumps(payload)}\n```"
        client = _mock_client(fenced)
        result = await extract_flowchart_structure(b"fake-webp", client=client)
        assert result.nodes[0].text == "Start"

    async def test_empty_bytes_rejected(self):
        client = _mock_client("{}")
        with pytest.raises(ValueError, match="non-empty"):
            await extract_flowchart_structure(b"", client=client)
        client.messages.create.assert_not_awaited()

    async def test_invalid_json_raises(self):
        client = _mock_client("not json")
        with pytest.raises(ValueError):
            await extract_flowchart_structure(b"fake-webp", client=client)

    async def test_missing_nodes_fails_validation(self):
        client = _mock_client(json.dumps({"edges": []}))
        with pytest.raises(ValidationError):
            await extract_flowchart_structure(b"fake-webp", client=client)

    async def test_empty_nodes_list_rejected(self):
        # nodes must be min_length=1 per the schema — reply missing content
        client = _mock_client(json.dumps({"nodes": [], "edges": []}))
        with pytest.raises(ValidationError):
            await extract_flowchart_structure(b"fake-webp", client=client)


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------


class TestTranslateStructure:
    async def test_preserves_ids_and_structure(self):
        source = FlowchartStructure(
            nodes=[
                FlowchartNode(id="n1", text="Make an observation"),
                FlowchartNode(id="n2", text="Ask a question"),
            ],
            edges=[FlowchartEdge(from_id="n1", to_id="n2")],
        )
        translated_payload = {
            "nodes": [
                {"id": "n1", "text": "Faire une observation", "shape": "rect"},
                {"id": "n2", "text": "Poser une question", "shape": "rect"},
            ],
            "edges": [{"from_id": "n1", "to_id": "n2"}],
        }
        client = _mock_client(json.dumps(translated_payload))
        out = await translate_structure(source, target_lang="fr", client=client)
        assert [n.id for n in out.nodes] == ["n1", "n2"]
        assert out.nodes[0].text == "Faire une observation"

    async def test_rejects_unsupported_target_lang(self):
        source = FlowchartStructure(nodes=[FlowchartNode(id="n1", text="x")])
        with pytest.raises(ValueError, match="unsupported target_lang"):
            await translate_structure(source, target_lang="de")

    async def test_raises_when_translator_changes_ids(self):
        source = FlowchartStructure(
            nodes=[FlowchartNode(id="n1", text="Start")],
            edges=[],
        )
        rogue_payload = {
            "nodes": [{"id": "node_1", "text": "Démarrer", "shape": "rect"}],
            "edges": [],
        }
        client = _mock_client(json.dumps(rogue_payload))
        with pytest.raises(ValueError, match="changed node ids"):
            await translate_structure(source, target_lang="fr", client=client)


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------


class TestRenderSvg:
    def _parse(self, svg_bytes: bytes) -> ET.Element:
        # Strips default namespace so findall is simpler
        text = svg_bytes.decode("utf-8").replace(' xmlns="http://www.w3.org/2000/svg"', "")
        return ET.fromstring(text)

    def test_basic_flowchart_renders_valid_xml(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="n1", text="Make an observation"),
                FlowchartNode(id="n2", text="Ask a question"),
            ],
            edges=[FlowchartEdge(from_id="n1", to_id="n2")],
        )
        svg = render_svg(structure)
        root = self._parse(svg)
        assert root.tag == "svg"
        rects = root.findall(".//rect")
        assert len(rects) == 2
        paths = root.findall(".//path")
        # one arrow marker defs path + one edge path
        assert len(paths) >= 2
        texts = {t.text for t in root.findall(".//text") if t.text}
        assert any("Make" in t for t in texts)
        assert any("Ask" in t for t in texts)

    def test_all_shapes_supported(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="r", text="rect", shape="rect"),
                FlowchartNode(id="d", text="diamond", shape="diamond"),
                FlowchartNode(id="e", text="ellipse", shape="ellipse"),
                FlowchartNode(id="p", text="par", shape="parallelogram"),
            ],
            edges=[],
        )
        svg = render_svg(structure)
        root = self._parse(svg)
        assert root.findall(".//rect")
        assert root.findall(".//ellipse")
        # polygon used for both diamond and parallelogram
        assert len(root.findall(".//polygon")) == 2

    def test_xml_special_chars_escaped(self):
        structure = FlowchartStructure(
            nodes=[FlowchartNode(id="n1", text='A & <B> "quote"')],
            edges=[],
        )
        svg = render_svg(structure)
        # must parse as valid XML
        root = self._parse(svg)
        texts = [t.text for t in root.findall(".//text") if t.text]
        assert any("A &" in t or "A &amp" in t for t in texts) or any("A & <B>" in t for t in texts)

    def test_edge_labels_rendered(self):
        structure = FlowchartStructure(
            nodes=[
                FlowchartNode(id="a", text="A"),
                FlowchartNode(id="b", text="B"),
            ],
            edges=[FlowchartEdge(from_id="a", to_id="b", label="Yes")],
        )
        svg = render_svg(structure)
        root = self._parse(svg)
        texts = {t.text for t in root.findall(".//text") if t.text}
        assert "Yes" in texts

    def test_empty_flowchart_raises(self):
        # Can't create via Pydantic (min_length=1), so test the renderer
        # directly with a pre-built object
        empty = FlowchartStructure.model_construct(nodes=[], edges=[])
        with pytest.raises(ValueError):
            render_svg(empty)

    def test_output_is_bytes(self):
        structure = FlowchartStructure(
            nodes=[FlowchartNode(id="n1", text="Start")],
            edges=[],
        )
        svg = render_svg(structure)
        assert isinstance(svg, bytes)
        assert svg.startswith(b"<svg")
