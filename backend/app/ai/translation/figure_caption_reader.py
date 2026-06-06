"""Read a figure's real caption from its image, and flag body-text crops (#2435).

The PyMuPDF extractor derives captions from page geometry, which fails two ways:
it leaves the caption empty (so the pipeline falls back to echoing the bare
figure number — "Figure 4.2"), and it sometimes rasterizes a whole page of body
text as a "figure". A cheap vision call fixes both at the source: it reads the
caption printed in the image and tells us whether the crop is actually a figure.

Runs on whichever provider ``settings.figure_vision_provider`` selects (default
Gemini 2.5 Flash-Lite). Gated by the same ``enable_figure_vision`` kill-switch.
"""

from __future__ import annotations

import json

import structlog
from pydantic import BaseModel, Field

from app.ai.translation.figure_classifier import _extract_json_object
from app.ai.translation.vision_provider import VisionProvider, get_vision_provider
from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)

_MAX_TOKENS = 300

_SYSTEM_PROMPT = (
    "You extract metadata from a single image cropped out of an academic "
    "textbook PDF. Reply with one JSON object and nothing else — no prose, no "
    "markdown fences."
)

_USER_PROMPT = (
    "This image was extracted as a figure from a textbook page. Return JSON with "
    "exactly two fields:\n"
    '  "caption": the figure\'s own caption sentence as printed in the image, '
    'VERBATIM but WITHOUT the leading label (drop any "Figure 4.2", "Fig. 1", '
    '"Table 3", "Schéma 2" prefix). If no descriptive caption text is visible, '
    "or the only text is the figure number itself, use null.\n"
    '  "is_body_text": true if this image is NOT a figure at all — i.e. it is a '
    "screenshot of running paragraph or multi-column body text, a page "
    "header/footer, or a block of references. false if it is a genuine figure, "
    "chart, diagram, table, photo, or formula.\n\n"
    'Reply with: {"caption": <string|null>, "is_body_text": <boolean>}'
)


class FigureCaptionRead(BaseModel):
    """Validated caption-reader output."""

    caption: str | None = Field(
        None, description="Caption text, label prefix removed; None if absent"
    )
    is_body_text: bool = Field(
        False, description="True when the image is page body-text, not a figure"
    )


async def read_figure_caption(
    image_bytes: bytes,
    image_media_type: str = "image/webp",
    provider: VisionProvider | None = None,
) -> FigureCaptionRead:
    """Read the real caption + body-text flag from a figure image.

    Args:
        image_bytes: Raw bytes of the figure asset (WebP as stored in MinIO).
        image_media_type: MIME type for the vision payload.
        provider: Optional injected provider (tests). Defaults to the configured one.

    Raises:
        ValueError: empty input or malformed model output.
        RuntimeError: figure vision disabled via the cost kill-switch.
    """
    if not image_bytes:
        raise ValueError("image_bytes must be non-empty")

    settings = get_settings()
    if not settings.enable_figure_vision:
        raise RuntimeError("figure vision is disabled (ENABLE_FIGURE_VISION=false)")

    if provider is None:
        provider = get_vision_provider()

    text = await provider.complete_json(
        image_bytes=image_bytes,
        image_media_type=image_media_type,
        system=_SYSTEM_PROMPT,
        user_prompt=_USER_PROMPT,
        max_tokens=_MAX_TOKENS,
    )
    if not text.strip():
        raise ValueError("empty caption-reader response")

    try:
        payload = json.loads(_extract_json_object(text))
    except json.JSONDecodeError as exc:
        logger.warning("Caption reader produced invalid JSON", preview=text[:200], error=str(exc))
        raise ValueError(f"caption reader returned invalid JSON: {exc}") from exc

    raw_caption = payload.get("caption") if isinstance(payload, dict) else None
    caption = raw_caption.strip() if isinstance(raw_caption, str) and raw_caption.strip() else None
    is_body_text = bool(payload.get("is_body_text")) if isinstance(payload, dict) else False
    return FigureCaptionRead(caption=caption, is_body_text=is_body_text)
