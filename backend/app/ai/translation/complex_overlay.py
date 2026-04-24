"""Re-derive a ``complex_diagram`` figure as a raster + numbered-badge overlay
+ French legend (issue #1883, Phase 2 slice 2.4).

``clean_flowchart`` figures can be rebuilt from scratch as SVG because the
source is already a clean logical graph (boxes + arrows). Complex diagrams —
anatomy plates, multi-panel figures, dense labelled illustrations — can't:
Claude Vision can't reproduce the imagery faithfully and a rebuild produces a
mangled copy. Strategy here is opposite: **keep the original raster untouched,
overlay small numbered badges on top of each translatable label, and put a
``1 — Noyau, 2 — Membrane...`` legend below the image**. Every label is
translated; the visual fidelity of the underlying figure is preserved.

Pipeline:

1. ``extract_label_positions`` — Claude Vision returns a list of labels with
   approximate percentage coordinates relative to the image (not pixel-
   accurate; badges just need to sit near the right area).
2. ``translate_labels`` — single Claude Haiku call translates the text of
   every label to the target locale, preserving ids and coordinates.
3. ``render_overlay_svg`` — produces one self-contained SVG:
   - the raster is embedded via a base64 ``<image href="data:image/webp;base64,...">``
   - numbered ``<circle>`` badges are drawn on top at each label's position
   - a legend strip below the image maps each badge number to its translated
     term.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)


class DiagramLabel(BaseModel):
    id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    # Percentage of image width/height. Claude Vision isn't pixel-accurate,
    # so we don't pretend — percentages keep the renderer independent of
    # the source image's resolution.
    x_pct: float
    y_pct: float

    @field_validator("x_pct", "y_pct", mode="before")
    @classmethod
    def _coerce_percentage(cls, value: Any) -> Any:
        # Tolerate integer literals ("45") and 0-1 fractions ("0.45") from
        # the model. Convert fractions to percentages so downstream code
        # has one invariant, then clamp near-edge overflows (Vision
        # occasionally returns 104.0 for a label touching the bottom
        # border) to the valid [0, 100] range instead of rejecting the
        # whole response.
        if isinstance(value, int | float):
            if 0.0 < value <= 1.0:
                value = float(value) * 100.0
            if value < 0.0:
                return 0.0
            if value > 100.0:
                return 100.0
        return value


class DiagramLabels(BaseModel):
    # Accept an empty list — Claude Vision legitimately returns zero labels
    # for diagrams that have no visible text (dense illustrations, photos
    # misclassified as complex_diagram). Callers handle the empty case by
    # reclassifying the source image to 'photo' (caption-only path).
    labels: list[DiagramLabel] = Field(default_factory=list)


_EXTRACT_MODEL = "claude-haiku-4-5"
_TRANSLATE_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 2048


_EXTRACT_SYSTEM = (
    "You locate every text label drawn ON TOP of a complex diagram image and "
    "return their approximate positions. Reply with a single JSON object and "
    "nothing else — no prose, no markdown fences."
)

_EXTRACT_USER = (
    "Find every text label that is drawn on or immediately next to a structure "
    "in this diagram. Return JSON:\n"
    '  {"labels": [{"id": "n1", "text": "...", "x_pct": 42.5, "y_pct": 17.0}, ...]}\n\n'
    "Rules:\n"
    "- ids are short stable identifiers you invent (n1, n2, …) in the order you\n"
    "  want them numbered in the final legend.\n"
    "- text is the label verbatim — preserve capitalisation, accents, and\n"
    "  punctuation. Do not invent, translate, or abbreviate.\n"
    "- x_pct / y_pct are the position of the label's leftmost character, as a\n"
    "  percentage (0–100) of the image's width and height. (0,0) is the top-\n"
    "  left corner. Approximate is fine; we just need the badge to land near\n"
    "  the label.\n"
    "- Include only labels that ARE text visible inside/next to the figure.\n"
    "  Skip figure captions / attribution / axis titles that live outside the\n"
    "  image proper. Skip any text that is part of a scale bar.\n"
    "- Do NOT return label order guesses, coordinates in pixels, or any other\n"
    "  field. Reply with JSON only."
)


_TRANSLATE_SYSTEM = (
    "You translate the text fields of a labelled diagram into the target "
    "language. Reply with a single JSON object and nothing else."
)

_TRANSLATE_USER_TEMPLATE = (
    "Translate every ``text`` field in this labelled diagram into "
    "{target_lang_full}. Preserve ids and coordinates byte-identical; only "
    "translate the text. Use natural terminology for the subject — if the "
    "label is a scientific term (anatomy, biology, chemistry) use the "
    "standard French term, not a literal translation.\n\n"
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


def _parse_labels(text: str) -> DiagramLabels:
    body = _extract_json_object(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"labels response was not valid JSON: {exc}") from exc
    try:
        return DiagramLabels(**payload)
    except ValidationError:
        logger.warning(
            "DiagramLabels failed validation",
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
        )
        raise


async def extract_label_positions(
    image_bytes: bytes,
    image_media_type: str = "image/webp",
    client: anthropic.AsyncAnthropic | None = None,
) -> DiagramLabels:
    """Claude Vision call: return every visible label + its approximate position."""
    if not image_bytes:
        raise ValueError("image_bytes must be non-empty")
    settings = get_settings()
    if not settings.enable_figure_vision:
        # Cost kill-switch (#1928). Caller catches and treats as a skip.
        raise RuntimeError("figure vision is disabled (ENABLE_FIGURE_VISION=false)")
    if client is None:
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to extract labels")
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
        raise ValueError("empty label-extraction response")
    return _parse_labels(text)


async def translate_labels(
    labels: DiagramLabels,
    target_lang: str = "fr",
    client: anthropic.AsyncAnthropic | None = None,
) -> DiagramLabels:
    """Translate every label's text into ``target_lang``, preserving ids and positions."""
    if target_lang not in {"fr", "en"}:
        raise ValueError(f"unsupported target_lang: {target_lang!r}")
    if client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to translate labels")
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,
        )

    target_full = {"fr": "French", "en": "English"}[target_lang]
    payload = labels.model_dump_json()
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
        raise ValueError("empty label-translation response")
    translated = _parse_labels(text)

    original_ids = {label.id for label in labels.labels}
    translated_ids = {label.id for label in translated.labels}
    if original_ids != translated_ids:
        raise ValueError(
            "translator changed label ids: "
            f"added={translated_ids - original_ids}, "
            f"removed={original_ids - translated_ids}"
        )
    return translated


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

_BADGE_RADIUS_FRACTION = 0.02  # fraction of min(width, height)
_BADGE_MIN_RADIUS = 10
_BADGE_MAX_RADIUS = 22
_LEGEND_FONT_SIZE = 14
_LEGEND_LINE_HEIGHT = 20
_LEGEND_PADDING = 20
_LEGEND_MAX_CHARS_PER_LINE = 80


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _wrap_legend_line(number: int, text: str, max_chars: int) -> list[str]:
    """Wrap a `N — text` line at word boundaries, returning visible lines."""
    prefix = f"{number} — "
    budget = max(1, max_chars - len(prefix))
    words = text.split()
    if not words:
        return [prefix.rstrip()]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= budget:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    # The first line includes the prefix; continuation lines are indented to
    # match visually.
    indent = " " * len(prefix)
    return [prefix + lines[0]] + [indent + line for line in lines[1:]]


def render_overlay_svg(
    image_bytes: bytes,
    width_px: int,
    height_px: int,
    labels: DiagramLabels,
    image_media_type: str = "image/webp",
) -> bytes:
    """Render a ``complex_diagram`` figure as raster + badge overlay + legend.

    Produces a single self-contained SVG document: the source raster is
    embedded base64, numbered badges sit on top at each label's position, and
    a legend strip below maps ``N — translated term`` for each badge.
    """
    if not image_bytes:
        raise ValueError("image_bytes must be non-empty")
    if width_px <= 0 or height_px <= 0:
        raise ValueError("width_px and height_px must be positive")
    if not labels.labels:
        raise ValueError("labels must be non-empty")

    badge_radius = max(
        _BADGE_MIN_RADIUS,
        min(_BADGE_MAX_RADIUS, int(min(width_px, height_px) * _BADGE_RADIUS_FRACTION)),
    )
    font_size_badge = max(10, int(badge_radius * 1.1))

    # Legend rows: one entry per label, possibly wrapping onto multiple lines.
    legend_lines: list[str] = []
    for i, label in enumerate(labels.labels, start=1):
        legend_lines.extend(_wrap_legend_line(i, label.text, _LEGEND_MAX_CHARS_PER_LINE))

    legend_height = _LEGEND_PADDING * 2 + len(legend_lines) * _LEGEND_LINE_HEIGHT
    total_height = height_px + legend_height

    encoded_image = base64.standard_b64encode(image_bytes).decode("ascii")

    svg_parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="0 0 {width_px} {total_height}" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="{_LEGEND_FONT_SIZE}">'
    ]

    # Base raster (encoded inline so the SVG is a self-contained asset).
    svg_parts.append(
        f'<image x="0" y="0" width="{width_px}" height="{height_px}" '
        f'xlink:href="data:{image_media_type};base64,{encoded_image}" />'
    )

    # Numbered badges over the raster.
    for i, label in enumerate(labels.labels, start=1):
        cx = round(label.x_pct / 100.0 * width_px, 2)
        cy = round(label.y_pct / 100.0 * height_px, 2)
        svg_parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{badge_radius}" '
            f'fill="#FFCA28" stroke="#5D4037" stroke-width="1.5" opacity="0.95" />'
        )
        svg_parts.append(
            f'<text x="{cx}" y="{cy + font_size_badge * 0.35:.2f}" '
            f'text-anchor="middle" font-size="{font_size_badge}" '
            f'font-weight="700" fill="#3E2723">{i}</text>'
        )

    # Legend strip below the image.
    svg_parts.append(
        f'<rect x="0" y="{height_px}" width="{width_px}" height="{legend_height}" '
        f'fill="#FAFAFA" stroke="#E0E0E0" stroke-width="1" />'
    )
    y = height_px + _LEGEND_PADDING + _LEGEND_FONT_SIZE
    for line in legend_lines:
        svg_parts.append(
            f'<text x="{_LEGEND_PADDING}" y="{y}" fill="#212121" '
            f'xml:space="preserve">{_escape(line)}</text>'
        )
        y += _LEGEND_LINE_HEIGHT

    svg_parts.append("</svg>")
    return "\n".join(svg_parts).encode("utf-8")
