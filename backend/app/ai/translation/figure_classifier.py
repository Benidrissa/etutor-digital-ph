"""Classify a figure into a Phase-2 routing kind via Claude Vision (issue #1844).

Given the WebP bytes of a figure extracted from a PDF, Claude Haiku with
vision returns one of a fixed set of ``FigureKind`` values. The value is
stored on ``source_images.figure_kind`` and later Phase-2 slices use it
to decide how (or whether) to produce a French variant:

- ``clean_flowchart`` / ``chart`` → slice 3 re-derives as SVG.
- ``complex_diagram`` → slice 4 produces raster + numbered-badge overlay.
- ``photo_with_callouts`` → slice 5 overlays translated callouts.
- ``photo`` / ``decorative`` → caption-only (already covered by Phase 1).
- ``formula`` / ``micrograph`` → never re-derive (caption-only).
- ``table`` → future slice may reconstruct as semantic HTML.

One Claude Haiku call per figure. The prompt enforces single JSON output;
the caller raises on failures rather than guessing a default.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Literal

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)


FigureKind = Literal[
    "clean_flowchart",
    "chart",
    "table",
    "photo",
    "photo_with_callouts",
    "formula",
    "micrograph",
    "decorative",
    "complex_diagram",
]

_ALLOWED_KINDS: set[str] = {
    "clean_flowchart",
    "chart",
    "table",
    "photo",
    "photo_with_callouts",
    "formula",
    "micrograph",
    "decorative",
    "complex_diagram",
}

_CLASSIFIER_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 128

_SYSTEM_PROMPT = (
    "You classify figures extracted from academic textbooks into one of a "
    "fixed set of kinds so that a downstream localisation pipeline can "
    "decide how to translate them. Reply with a single JSON object and "
    "nothing else — no prose, no markdown fences."
)

_USER_PROMPT = (
    "Classify this figure into exactly ONE of these kinds:\n\n"
    "- clean_flowchart: boxes/ovals connected by arrows, clearly readable\n"
    "  text labels inside each node. Typically used for processes, "
    "decision flows, algorithms.\n"
    "- chart: bar/line/pie/scatter chart with axes, labels, a legend. "
    "Data visualisation, not a flow.\n"
    "- table: a grid of rows and columns with header cells. Tabular data.\n"
    "- photo: a real photograph with no embedded text labels.\n"
    "- photo_with_callouts: a photograph or micrograph with arrows / "
    "leader lines pointing to labelled features.\n"
    "- formula: a typeset mathematical or chemical equation.\n"
    "- micrograph: a microscopy image (cells, tissue, crystals), with or "
    "without arrows. Prefer this over 'photo_with_callouts' when the "
    "image itself is microscopy.\n"
    "- decorative: small icon, border, or purely visual element carrying "
    "no information.\n"
    "- complex_diagram: anatomical plate, multi-panel figure, dense "
    "labelled illustration with many text annotations. Anything that is "
    "clearly a diagram but too dense for clean_flowchart.\n\n"
    "Reply with a JSON object containing exactly one field:\n"
    '  {"kind": "<one of the values above>"}\n\n'
    "Rules:\n"
    "- Pick the single best fit. If torn between two, prefer the more "
    "conservative classification (e.g. complex_diagram over "
    "clean_flowchart when in doubt, photo over photo_with_callouts).\n"
    "- Do not invent new kinds. Reply with JSON only."
)


class FigureClassification(BaseModel):
    """Validated classifier output."""

    kind: FigureKind = Field(..., description="One of the allowed FigureKind values.")


def _extract_json_object(text: str) -> str:
    """Strip markdown fences and isolate the first JSON object in the response."""
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
        raise ValueError("no JSON object in classifier response")
    body = clean[start : end + 1]
    return re.sub(r",\s*([}\]])", r"\1", body)


async def classify_figure(
    image_bytes: bytes,
    image_media_type: str = "image/webp",
    client: anthropic.AsyncAnthropic | None = None,
) -> FigureClassification:
    """Classify a figure into a :data:`FigureKind`.

    Args:
        image_bytes: Raw bytes of the figure asset (WebP as stored in MinIO).
        image_media_type: MIME type for the Anthropic vision payload.
            Defaults to the project's WebP storage format.
        client: Optional injected ``AsyncAnthropic`` client (for tests).

    Returns:
        :class:`FigureClassification` — ``.kind`` guaranteed to be one of
        the allowed values (validated by Pydantic's ``Literal`` typing).

    Raises:
        ValueError: empty input, malformed model output, or unknown kind.
        ValidationError: model output parsed but fails schema validation.
    """
    if not image_bytes:
        raise ValueError("image_bytes must be non-empty")

    if client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to classify figures")
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,
        )

    encoded = base64.standard_b64encode(image_bytes).decode("ascii")
    response = await client.messages.create(
        model=_CLASSIFIER_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
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
                    {"type": "text", "text": _USER_PROMPT},
                ],
            }
        ],
        temperature=0.0,
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    if not text.strip():
        raise ValueError("empty classifier response")

    body = _extract_json_object(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Figure classifier produced invalid JSON",
            preview=text[:200],
            error=str(exc),
        )
        raise ValueError(f"classifier returned invalid JSON: {exc}") from exc

    if isinstance(payload, dict):
        kind = payload.get("kind")
        if kind is not None and kind not in _ALLOWED_KINDS:
            logger.warning(
                "Classifier returned unknown kind; rejecting",
                kind=kind,
            )
            raise ValueError(f"classifier returned unknown kind: {kind!r}")

    try:
        return FigureClassification(**payload)
    except ValidationError as exc:
        logger.warning(
            "Figure classifier response failed validation",
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
        )
        raise exc
