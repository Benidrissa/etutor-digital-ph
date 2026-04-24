"""Re-derive a ``clean_flowchart`` figure as a translated SVG (issue #1852).

Pipeline:

1. ``extract_flowchart_structure`` — Claude Vision returns a logical graph of
   nodes and edges (no pixel coordinates, no layout).
2. ``translate_structure`` — Claude Haiku translates every ``nodes[].text``
   and ``edges[].label`` into the target locale, preserving ids + shapes.
3. ``render_svg`` — deterministic Python SVG emission. Auto-lays nodes on a
   top-down DAG grid (row per layer), draws edges as arrowed paths.

Returning a "tidied" layout rather than mimicking the PDF's pixel layout is a
deliberate trade-off: Claude Vision can't reliably reproduce coordinates,
and a clean rebuild beats a visually mangled copy.

Only ``clean_flowchart`` is handled in this slice; charts/tables/complex
diagrams come in later slices.
"""

from __future__ import annotations

import base64
import json
import re
from collections import defaultdict, deque
from typing import Literal

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)


NodeShape = Literal["rect", "diamond", "ellipse", "parallelogram"]


class FlowchartNode(BaseModel):
    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    shape: NodeShape = "rect"


class FlowchartEdge(BaseModel):
    from_id: str = Field(..., min_length=1)
    to_id: str = Field(..., min_length=1)
    label: str | None = None


class FlowchartStructure(BaseModel):
    nodes: list[FlowchartNode] = Field(..., min_length=1)
    edges: list[FlowchartEdge] = Field(default_factory=list)


_EXTRACT_MODEL = "claude-haiku-4-5"
_TRANSLATE_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 2048


_EXTRACT_SYSTEM = (
    "You extract the logical structure of a flowchart from an image. You reply "
    "with a single JSON object and nothing else — no prose, no markdown fences."
)

_EXTRACT_USER = (
    "Extract this flowchart's structure as a directed graph. Return JSON:\n"
    '  {"nodes": [{"id": "n1", "text": "...", "shape": "rect"}, ...],\n'
    '   "edges": [{"from_id": "n1", "to_id": "n2", "label": null}, ...]}\n\n'
    "Rules:\n"
    "- ids are short stable identifiers you invent (n1, n2, ...). Order them\n"
    "  so that the entry point is first.\n"
    "- text is the full label the box contains, verbatim. Preserve capitalisation,\n"
    "  punctuation, and line breaks (keep '\\n' between lines if the box has "
    "multiple lines).\n"
    "- shape is one of: rect (rectangle), diamond (decision), ellipse "
    "(start/end), parallelogram (input/output). If unsure pick rect.\n"
    "- edges list every arrow. label is the text on the arrow if any, else null.\n"
    "- Do NOT include coordinates, sizes, colors, or styles — only the logical\n"
    "  graph. The renderer computes layout.\n"
    "- Reply with JSON only."
)


_TRANSLATE_SYSTEM = (
    "You translate flowchart labels into the target language. You reply with a "
    "single JSON object and nothing else — no prose, no markdown fences."
)

_TRANSLATE_USER_TEMPLATE = (
    "Translate every text field in this flowchart structure into {target_lang_full}. "
    "Preserve ids, shapes, and the edges array shape. Keep the JSON structure "
    "byte-identical except for translated strings. Preserve capitalisation style "
    "and punctuation conventions of the target language.\n\n"
    "Input:\n{payload}\n\n"
    "Reply with the translated JSON only."
)


def _extract_json_object(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        first_newline = clean.find("\n")
        if first_newline > 0:
            clean = clean[first_newline + 1 :]
        if clean.rstrip().endswith("```"):
            clean = clean.rstrip()[:-3]
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    body = clean[start : end + 1]
    return re.sub(r",\s*([}\]])", r"\1", body)


def _parse_structure(text: str) -> FlowchartStructure:
    body = _extract_json_object(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"structure response was not valid JSON: {exc}") from exc
    try:
        return FlowchartStructure(**payload)
    except ValidationError as exc:
        logger.warning(
            "Flowchart structure failed validation",
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
        )
        raise exc


async def extract_flowchart_structure(
    image_bytes: bytes,
    image_media_type: str = "image/webp",
    client: anthropic.AsyncAnthropic | None = None,
) -> FlowchartStructure:
    """Run Claude Vision to extract the logical graph of a flowchart."""
    if not image_bytes:
        raise ValueError("image_bytes must be non-empty")

    settings = get_settings()
    if not settings.enable_figure_vision:
        # Cost kill-switch (#1928). Caller catches and treats as a skip.
        raise RuntimeError("figure vision is disabled (ENABLE_FIGURE_VISION=false)")

    if client is None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to extract flowcharts")
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=90.0,
        )

    encoded = base64.standard_b64encode(image_bytes).decode("ascii")
    response = await client.messages.create(
        model=_EXTRACT_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_EXTRACT_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_media_type,
                            "data": encoded,
                        },
                    },
                    {"type": "text", "text": _EXTRACT_USER},
                ],
            }
        ],
        temperature=0.0,
    )

    text = "".join(
        getattr(block, "text", "") for block in response.content if hasattr(block, "text")
    )
    if not text.strip():
        raise ValueError("empty flowchart-structure response")
    return _parse_structure(text)


async def translate_structure(
    structure: FlowchartStructure,
    target_lang: str = "fr",
    client: anthropic.AsyncAnthropic | None = None,
) -> FlowchartStructure:
    """Translate the text fields of a flowchart structure into ``target_lang``."""
    if target_lang not in {"fr", "en"}:
        raise ValueError(f"unsupported target_lang: {target_lang!r}")

    if client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to translate flowcharts")
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,
        )

    target_full = {"fr": "French", "en": "English"}[target_lang]
    payload = structure.model_dump_json()
    response = await client.messages.create(
        model=_TRANSLATE_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_TRANSLATE_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": _TRANSLATE_USER_TEMPLATE.format(
                    target_lang_full=target_full, payload=payload
                ),
            }
        ],
        temperature=0.0,
    )
    text = "".join(
        getattr(block, "text", "") for block in response.content if hasattr(block, "text")
    )
    if not text.strip():
        raise ValueError("empty translate-structure response")
    translated = _parse_structure(text)

    original_ids = {n.id for n in structure.nodes}
    translated_ids = {n.id for n in translated.nodes}
    if original_ids != translated_ids:
        raise ValueError(
            "translator changed node ids: "
            f"added={translated_ids - original_ids}, "
            f"removed={original_ids - translated_ids}"
        )
    return translated


# ---------------------------------------------------------------------------
# SVG rendering — deterministic, no external renderer
# ---------------------------------------------------------------------------

_NODE_WIDTH = 220
_NODE_HEIGHT = 70
_COLUMN_GAP = 40
_ROW_GAP = 50
_PADDING = 40
_FONT_SIZE = 14
_MAX_CHARS_PER_LINE = 28


def _assign_layers(structure: FlowchartStructure) -> dict[str, int]:
    """Assign every node a non-negative layer via topological BFS.

    Nodes with no incoming edges are layer 0; downstream nodes go one
    layer deeper via longest-path relaxation. A ``visited`` set guards
    against cycles: each node is processed at most once, so back-edges
    in cyclic flowcharts do NOT cause infinite re-queueing. Nodes that
    sit entirely inside a cycle (unreachable from any source) are
    seeded via the first node and eventually default to layer 0.
    """
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    ids = {n.id for n in structure.nodes}
    for e in structure.edges:
        if e.from_id in ids and e.to_id in ids:
            incoming[e.to_id].append(e.from_id)
            outgoing[e.from_id].append(e.to_id)

    layer: dict[str, int] = {}
    queue: deque[str] = deque()
    for n in structure.nodes:
        if not incoming[n.id]:
            layer[n.id] = 0
            queue.append(n.id)

    # Fallback: if every node has an incoming edge (cycle at the top),
    # seed with the first node as layer 0.
    if not queue and structure.nodes:
        layer[structure.nodes[0].id] = 0
        queue.append(structure.nodes[0].id)

    visited: set[str] = set()
    while queue:
        current = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        for nxt in outgoing[current]:
            candidate = layer[current] + 1
            if nxt not in layer or (candidate > layer[nxt] and nxt not in visited):
                layer[nxt] = candidate
                queue.append(nxt)

    # Anything still unassigned (isolated in a pure cycle) gets layer 0.
    for n in structure.nodes:
        layer.setdefault(n.id, 0)

    return layer


def _wrap(text: str, max_chars: int = _MAX_CHARS_PER_LINE) -> list[str]:
    """Wrap text into lines, respecting explicit ``\\n`` first, then word breaks."""
    lines: list[str] = []
    for raw in text.split("\n"):
        words = raw.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= max_chars:
                current = f"{current} {word}"
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_shape(node: FlowchartNode, cx: float, cy: float) -> str:
    half_w = _NODE_WIDTH / 2
    half_h = _NODE_HEIGHT / 2
    if node.shape == "ellipse":
        return (
            f'<ellipse cx="{cx}" cy="{cy}" rx="{half_w}" ry="{half_h}" '
            f'fill="#D5E8D4" stroke="#82B366" stroke-width="1.5" />'
        )
    if node.shape == "diamond":
        pts = f"{cx},{cy - half_h} {cx + half_w},{cy} {cx},{cy + half_h} {cx - half_w},{cy}"
        return f'<polygon points="{pts}" fill="#FFF2CC" stroke="#D6B656" stroke-width="1.5" />'
    if node.shape == "parallelogram":
        skew = 18
        pts = (
            f"{cx - half_w + skew},{cy - half_h} "
            f"{cx + half_w},{cy - half_h} "
            f"{cx + half_w - skew},{cy + half_h} "
            f"{cx - half_w},{cy + half_h}"
        )
        return f'<polygon points="{pts}" fill="#DAE8FC" stroke="#6C8EBF" stroke-width="1.5" />'
    # default rect
    return (
        f'<rect x="{cx - half_w}" y="{cy - half_h}" '
        f'width="{_NODE_WIDTH}" height="{_NODE_HEIGHT}" rx="6" '
        f'fill="#F5F5F5" stroke="#666666" stroke-width="1.5" />'
    )


# Reserved strip on the right side of the canvas used by back-edges
# (loopbacks) to route cleanly without crossing the main column. If no
# back-edges are present the strip stays empty but the extra whitespace
# is harmless.
_MARGIN_X = 60


def _forward_path(x1: float, y1_bottom: float, x2: float, y2_top: float) -> str:
    """Orthogonal path from the bottom edge of one box to the top edge of another,
    preferring a straight vertical line when the two boxes share an x column."""
    if abs(x1 - x2) < 1:
        return f"M{x1},{y1_bottom} L{x2},{y2_top}"
    mid_y = (y1_bottom + y2_top) / 2
    return f"M{x1},{y1_bottom} L{x1},{mid_y} L{x2},{mid_y} L{x2},{y2_top}"


def _sideways_path(x1_side: float, y1: float, x2_side: float, y2: float) -> str:
    """Horizontal path between two boxes on the same row (rare; used when two
    nodes share a layer and we have an explicit side edge)."""
    return f"M{x1_side},{y1} L{x2_side},{y2}"


def _back_path(
    x1_right: float,
    y1: float,
    x2_right: float,
    y2: float,
    margin_x: float,
) -> str:
    """Back-edge route: exit the right side of the source, rise up the right
    margin strip, and re-enter the right side of the target. The terminal
    segment goes leftward so ``orient="auto"`` points the arrow correctly."""
    return f"M{x1_right},{y1} L{margin_x},{y1} L{margin_x},{y2} L{x2_right},{y2}"


def render_svg(structure: FlowchartStructure) -> bytes:
    """Render a FlowchartStructure into a self-contained SVG document.

    Layout strategy:

    - Nodes are packed into layers via :func:`_assign_layers` (top-down DAG).
    - Forward edges (source layer < target layer) are drawn as orthogonal
      paths — a single straight vertical when the boxes share a column, an
      elbow (vertical / horizontal / vertical) otherwise.
    - Back-edges (source layer > target layer, i.e. loopbacks) are routed
      along a reserved right-margin strip so they never cross the main
      flow column.
    - Same-layer edges take a short horizontal path between box sides.
    """
    if not structure.nodes:
        raise ValueError("cannot render empty flowchart")

    layers = _assign_layers(structure)
    by_layer: dict[int, list[FlowchartNode]] = defaultdict(list)
    for node in structure.nodes:
        by_layer[layers[node.id]].append(node)

    max_nodes_per_layer = max(len(v) for v in by_layer.values())
    content_width = (
        _PADDING * 2 + max_nodes_per_layer * _NODE_WIDTH + (max_nodes_per_layer - 1) * _COLUMN_GAP
    )
    # Reserve a back-edge strip on the right; cheap (~60 px) even if no
    # back-edges appear — keeps layout calculation deterministic.
    width = content_width + _MARGIN_X
    height = _PADDING * 2 + len(by_layer) * _NODE_HEIGHT + (len(by_layer) - 1) * _ROW_GAP
    margin_x = content_width + _MARGIN_X / 2  # centre of the margin strip

    positions: dict[str, tuple[float, float]] = {}
    for layer_idx in sorted(by_layer.keys()):
        layer_nodes = by_layer[layer_idx]
        row_width = len(layer_nodes) * _NODE_WIDTH + (len(layer_nodes) - 1) * _COLUMN_GAP
        start_x = (content_width - row_width) / 2 + _NODE_WIDTH / 2
        cy = _PADDING + layer_idx * (_NODE_HEIGHT + _ROW_GAP) + _NODE_HEIGHT / 2
        for i, node in enumerate(layer_nodes):
            cx = start_x + i * (_NODE_WIDTH + _COLUMN_GAP)
            positions[node.id] = (cx, cy)

    svg_parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {int(width)} {int(height)}" '
        f'font-family="Helvetica, Arial, sans-serif" '
        f'font-size="{_FONT_SIZE}">',
        "<defs>"
        '<marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3" '
        'orient="auto" markerUnits="strokeWidth">'
        '<path d="M0,0 L0,6 L9,3 z" fill="#444" />'
        "</marker>"
        "</defs>",
    ]

    half_w = _NODE_WIDTH / 2
    half_h = _NODE_HEIGHT / 2

    # Edges first so nodes overdraw them cleanly.
    for edge in structure.edges:
        if edge.from_id not in positions or edge.to_id not in positions:
            continue
        cx1, cy1 = positions[edge.from_id]
        cx2, cy2 = positions[edge.to_id]
        src_layer = layers[edge.from_id]
        tgt_layer = layers[edge.to_id]

        if tgt_layer > src_layer:
            # Forward edge — orthogonal path from bottom to top.
            y1 = cy1 + half_h
            y2 = cy2 - half_h
            d = _forward_path(cx1, y1, cx2, y2)
            label_x = (cx1 + cx2) / 2
            label_y = (y1 + y2) / 2 - 4
        elif tgt_layer < src_layer:
            # Back edge — route via the right margin strip.
            x1 = cx1 + half_w
            x2 = cx2 + half_w
            d = _back_path(x1, cy1, x2, cy2, margin_x)
            label_x = margin_x
            label_y = (cy1 + cy2) / 2 - 4
        else:
            # Same layer — short horizontal between right of source and
            # left of target (or mirrored if target is left of source).
            if cx2 >= cx1:
                x1 = cx1 + half_w
                x2 = cx2 - half_w
            else:
                x1 = cx1 - half_w
                x2 = cx2 + half_w
            d = _sideways_path(x1, cy1, x2, cy2)
            label_x = (x1 + x2) / 2
            label_y = cy1 - 4

        svg_parts.append(
            f'<path d="{d}" stroke="#444" stroke-width="1.5" '
            'fill="none" marker-end="url(#arrow)" />'
        )
        if edge.label:
            svg_parts.append(
                f'<text x="{label_x}" y="{label_y}" text-anchor="middle" '
                f'fill="#666" font-size="{_FONT_SIZE - 2}">'
                f"{_escape(edge.label)}</text>"
            )

    for node in structure.nodes:
        cx, cy = positions[node.id]
        svg_parts.append(_render_shape(node, cx, cy))
        lines = _wrap(node.text)
        # Vertically centre the block of lines on cy.
        total_h = len(lines) * (_FONT_SIZE + 2)
        start_y = cy - total_h / 2 + _FONT_SIZE
        for i, line in enumerate(lines):
            y = start_y + i * (_FONT_SIZE + 2)
            svg_parts.append(
                f'<text x="{cx}" y="{y}" text-anchor="middle" fill="#222">{_escape(line)}</text>'
            )

    svg_parts.append("</svg>")
    return "\n".join(svg_parts).encode("utf-8")
