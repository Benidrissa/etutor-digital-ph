"""Translate a figure's caption + alt text to FR/EN (issue #1820).

Given the raw caption extracted from a PDF (usually English, but the source
language is not guaranteed), produce the four locale strings stored on
``source_images``:

- ``caption_fr`` / ``caption_en`` — visible figure label per locale
- ``alt_text_fr`` / ``alt_text_en`` — descriptive text for screen readers

One Claude Haiku call per figure. The prompt asks for a single JSON object
so the whole pipeline is: prompt → API call → ``json.loads`` → Pydantic
validation → return. The caller decides what to do with failures; the
translator raises, it does not swallow.
"""

from __future__ import annotations

import json
import re

import anthropic
import structlog
from pydantic import BaseModel, Field, ValidationError

from app.infrastructure.config.settings import get_settings

logger = structlog.get_logger(__name__)


_TRANSLATOR_MODEL = "claude-haiku-4-5"
_MAX_TOKENS = 512

_SYSTEM_PROMPT = (
    "You translate figure captions extracted from academic textbooks into "
    "French and English, and generate short descriptive alt text for screen "
    "readers in both languages. You reply with a single JSON object and "
    "nothing else — no prose, no markdown fences."
)

_USER_PROMPT_TEMPLATE = (
    "Raw caption text extracted from a textbook figure:\n"
    '"""{caption}"""\n\n'
    "Figure metadata (may be partial or missing):\n"
    "- figure number: {figure_number}\n"
    "- image type: {image_type}\n\n"
    "Produce a JSON object with exactly these four string fields:\n"
    "  caption_fr: the caption in natural French. If the source is already "
    "French, normalise it; otherwise translate faithfully.\n"
    "  caption_en: the caption in natural English. Translate from French "
    "if needed.\n"
    "  alt_text_fr: a short French description (1 sentence, max ~160 chars) "
    "suitable for a screen reader — describe what the figure shows, not "
    "just the caption.\n"
    "  alt_text_en: the same in English.\n\n"
    "Preserve scientific terms, proper nouns, and figure numbers verbatim. "
    "Do not add quotation marks around the output strings. Do not include "
    "the figure number inside the caption fields unless the source caption "
    "contained it. Reply with JSON only."
)


class FigureTranslation(BaseModel):
    """Validated translator output."""

    caption_fr: str = Field(..., min_length=1)
    caption_en: str = Field(..., min_length=1)
    alt_text_fr: str = Field(..., min_length=1)
    alt_text_en: str = Field(..., min_length=1)


def _build_user_prompt(
    caption: str,
    image_type: str | None,
    figure_number: str | None,
) -> str:
    return _USER_PROMPT_TEMPLATE.format(
        caption=caption.strip(),
        figure_number=figure_number or "(none)",
        image_type=image_type or "unknown",
    )


def _extract_json_object(text: str) -> str:
    """Best-effort isolation of a JSON object from a Claude response.

    Claude Haiku with a firm 'JSON only' system prompt almost always
    complies, but occasionally wraps the reply in markdown fences. Strip
    the fences and slice from the first ``{`` to the last ``}`` before
    handing off to ``json.loads``.
    """
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
        raise ValueError("no JSON object in translator response")
    body = clean[start : end + 1]
    return re.sub(r",\s*([}\]])", r"\1", body)


async def translate_figure_caption(
    caption: str,
    image_type: str | None = None,
    figure_number: str | None = None,
    client: anthropic.AsyncAnthropic | None = None,
) -> FigureTranslation:
    """Translate a figure caption into FR/EN caption + alt text.

    Args:
        caption: Raw caption text extracted from the PDF. If empty / whitespace,
            a ``ValueError`` is raised — translation is meaningless.
        image_type: ``diagram`` / ``photo`` / ``chart`` / etc. Passed to the
            model as context so alt text can match the figure kind.
        figure_number: e.g. ``"1.2"`` from ``"Figure 1.2"``. Optional.
        client: Injectable ``AsyncAnthropic`` client for tests.

    Returns:
        :class:`FigureTranslation` with all four non-empty locale strings.

    Raises:
        ValueError: empty caption or malformed model output.
        ValidationError: model output parsed but fails schema validation.
    """
    if not caption or not caption.strip():
        raise ValueError("caption must be non-empty")

    if client is None:
        settings = get_settings()
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required to translate figures")
        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key,
            timeout=60.0,
        )

    user_prompt = _build_user_prompt(caption, image_type, figure_number)
    response = await client.messages.create(
        model=_TRANSLATOR_MODEL,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=0.0,
    )

    text = ""
    for block in response.content:
        if hasattr(block, "text"):
            text += block.text
    if not text.strip():
        raise ValueError("empty translator response")

    body = _extract_json_object(text)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning(
            "Figure translator produced invalid JSON",
            figure_number=figure_number,
            preview=text[:200],
            error=str(exc),
        )
        raise ValueError(f"translator returned invalid JSON: {exc}") from exc

    try:
        return FigureTranslation(**payload)
    except ValidationError as exc:
        logger.warning(
            "Figure translator response failed validation",
            figure_number=figure_number,
            payload_keys=list(payload.keys()) if isinstance(payload, dict) else None,
        )
        raise exc
