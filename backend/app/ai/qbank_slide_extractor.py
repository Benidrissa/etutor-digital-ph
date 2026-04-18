"""PDF slide extraction for question bank — extracts image-based MCQs from PDF slides.

Each PDF page is a slide with a traffic situation photo and 1-2 MCQ questions.

Hybrid extraction pipeline (cost-optimized):

    Tier 1 — PyMuPDF text + color extraction (FREE, ~90% of pages)
        Reads text spans directly with get_text('dict'). Detects correct answers
        from the green color of option spans (no AI needed).

    Tier 3 — Claude Vision (EXPENSIVE, fallback for low-confidence pages)
        Only invoked when Tier 1 confidence < CONFIDENCE_THRESHOLD or when the
        PDF page has no extractable text (scanned).

Tier 2 (OCR for scanned PDFs) is not yet implemented — it would require adding
pytesseract + tesseract-ocr system packages. Scanned PDFs currently fall straight
through to Tier 3.
"""

from __future__ import annotations

import base64
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
import structlog
from PIL import Image

from app.ai.claude_service import ClaudeService

logger = structlog.get_logger(__name__)

RASTERIZE_DPI = 200
WEBP_MAX_WIDTH = 1024
WEBP_QUALITY = 87

# If Tier 1 confidence is below this, escalate to Tier 3 (Vision).
CONFIDENCE_THRESHOLD = 0.6

# Minimum length for a question text span to count as a question.
MIN_QUESTION_TEXT_LEN = 10

# Vertical gap (pt) between text spans that signals a new question cluster.
QUESTION_CLUSTER_GAP_PT = 40.0

# Regex for option labels: "A.", "A)", "a.", "1.", "1)"
OPTION_LABEL_RE = re.compile(r"^\s*([A-Da-d]|[1-4])[\.\)]\s+")

# FR keyword hints per category. Matched case- and diacritic-insensitively so
# "priorité" and "priorite" both match the "priorite" key. Used by Tier 1 to
# set a best-guess category without an AI call. Tier 3 (Vision) still classifies
# via the model prompt.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "signalisation": (
        "panneau",
        "signal",
        "feu",
        "feux",
        "stop",
        "ceder",
        "marquage",
        "ligne continue",
        "ligne discontinue",
    ),
    "priorite": (
        "priorite",
        "ceder le passage",
        "intersection",
        "carrefour",
        "rond-point",
        "rond point",
        "giratoire",
    ),
    "securite": (
        "ceinture",
        "casque",
        "airbag",
        "securite",
        "distance de securite",
        "alcool",
        "telephone",
        "fatigue",
    ),
    "stationnement": (
        "stationner",
        "stationnement",
        "garer",
        "parking",
        "arret",
    ),
    "vitesse": (
        "vitesse",
        "km/h",
        "kilometres",
        "ralentir",
        "acceler",
        "freinage",
    ),
    "pieton": (
        "pieton",
        "passage pieton",
        "trottoir",
    ),
    "cycliste": (
        "cycliste",
        "velo",
        "piste cyclable",
        "bicyclette",
    ),
}


def _normalize_for_match(text: str) -> str:
    """Lowercase + strip diacritics for substring matching."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _infer_category(question_text: str, options: list[str]) -> str:
    """Heuristic category classifier for Tier 1.

    Scans the question text and option texts for keyword hits from
    CATEGORY_KEYWORDS. Returns the category with the most hits, or "general" if
    no keywords match. Matching is case- and diacritic-insensitive.
    """
    haystack = _normalize_for_match(" ".join([question_text, *options]))

    best_category = "general"
    best_hits = 0
    for category, keywords in CATEGORY_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in haystack)
        if hits > best_hits:
            best_hits = hits
            best_category = category
    return best_category


EXTRACTION_SYSTEM_PROMPT = """You are analyzing a driving school exam or test preparation slide.
Extract ALL questions from this slide image. Each slide may contain 1 or 2 questions.

For each question found, extract:
1. question_text: The question being asked (in the original language)
2. options: Array of answer option texts (A, B, C, D — as many as present)
3. correct_indices: Array of 0-based indices of correct answers.
   Correct answers are usually in green or bold. If unknown, return [].
4. explanation: Brief explanation of why the answer is correct
5. category: One of: signalisation, priorite, securite,
   stationnement, vitesse, pieton, cycliste, general

Return a JSON array of questions. Example:
[{
  "question_text": "À vélo, que dois-tu faire ici ?",
  "options": ["Tu ralentis et tu passes.", "Tu t'arrêtes en mettant le pied à terre."],
  "correct_indices": [1],
  "explanation": "Le panneau STOP oblige à s'arrêter complètement.",
  "category": "signalisation"
}]

Important:
- Return ONLY valid JSON, no markdown or explanation outside the JSON
- If a slide has no questions (title slide, blank, etc.), return an empty array []
- Preserve the original language of the text (usually French)
"""


@dataclass
class ExtractedSlideQuestion:
    """A question extracted from a PDF slide."""

    question_text: str
    options: list[str]
    correct_indices: list[int]
    explanation: str | None
    category: str | None
    page_number: int
    image_bytes: bytes
    image_width: int
    image_height: int


@dataclass
class ExtractionStats:
    """Counters reported at the end of a PDF run."""

    total_pages: int = 0
    tier1_pages: int = 0  # Resolved by PyMuPDF (free)
    tier3_pages: int = 0  # Escalated to Claude Vision
    failed_pages: list[int] = field(default_factory=list)

    def log(self, logger_) -> None:
        logger_.info(
            "Slide extraction stats",
            total_pages=self.total_pages,
            tier1_free=self.tier1_pages,
            tier3_vision=self.tier3_pages,
            failed=len(self.failed_pages),
            tier1_pct=round(100 * self.tier1_pages / max(self.total_pages, 1), 1),
        )


def _rasterize_page(page: pymupdf.Page, dpi: int = RASTERIZE_DPI) -> bytes:
    """Rasterize a PDF page to PNG bytes at the given DPI."""
    mat = pymupdf.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _convert_to_webp(
    image_bytes: bytes,
    max_width: int = WEBP_MAX_WIDTH,
) -> tuple[bytes, int, int]:
    """Convert image bytes to WebP, capping width."""
    img = Image.open(io.BytesIO(image_bytes))

    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    if img.width > max_width:
        ratio = max_width / img.width
        new_height = max(1, int(img.height * ratio))
        img = img.resize((max_width, new_height), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue(), img.width, img.height


# Fallback crop ratio when the page has no text layer (fully scanned slides).
# Driving-school layouts reliably place the illustration in the top ~55%.
DEFAULT_ILLUSTRATION_RATIO = 0.55

# Clamp the crop ratio so we never cut off the illustration or keep too much
# of the text block.
MIN_ILLUSTRATION_RATIO = 0.3
MAX_ILLUSTRATION_RATIO = 0.75

# Text spans shorter than this are treated as headers (e.g. "Question 01")
# and ignored when picking the question-text top boundary.
HEADER_SPAN_MAX_LEN = 12

# Skip spans whose top is in the first ~10% of the page height — those are
# page headers, not the question block.
TOP_MARGIN_IGNORE_RATIO = 0.1


def _illustration_crop_ratio(page: pymupdf.Page) -> float:
    """Return the fraction of the page height that contains the illustration.

    For slides where the question/options text sits below the photo, this is
    the y-coordinate of the topmost question-looking text span divided by
    the page height. Falls back to ``DEFAULT_ILLUSTRATION_RATIO`` when no
    text layer is present (scanned slides).
    """
    spans = _flatten_spans(page.get_text("dict"))
    page_h = max(float(page.rect.height), 1.0)
    if not spans:
        return DEFAULT_ILLUSTRATION_RATIO

    for span in spans:
        text = span["text"].strip()
        if len(text) < HEADER_SPAN_MAX_LEN:
            continue
        y0 = float(span["bbox"][1])
        if y0 / page_h < TOP_MARGIN_IGNORE_RATIO:
            continue
        # Leave 2% padding above the text so we don't clip the illustration.
        ratio = (y0 / page_h) - 0.02
        return max(MIN_ILLUSTRATION_RATIO, min(MAX_ILLUSTRATION_RATIO, ratio))
    return DEFAULT_ILLUSTRATION_RATIO


def _crop_to_illustration(
    image_bytes: bytes,
    max_width: int = WEBP_MAX_WIDTH,
    crop_ratio: float = DEFAULT_ILLUSTRATION_RATIO,
) -> tuple[bytes, int, int]:
    """Crop a full-slide raster to the illustration region and encode as WebP.

    Driving-school PDFs frequently ship each slide as one image with the
    question text and options baked in. The frontend renders the extracted
    text separately, so keeping the text in the image duplicates the same
    information twice (#1669). This helper drops the bottom of the image.
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode not in ("RGB",):
        img = img.convert("RGB")

    crop_ratio = max(MIN_ILLUSTRATION_RATIO, min(MAX_ILLUSTRATION_RATIO, crop_ratio))
    new_h = max(1, int(img.height * crop_ratio))
    img = img.crop((0, 0, img.width, new_h))

    if img.width > max_width:
        ratio = max_width / img.width
        new_height = max(1, int(img.height * ratio))
        img = img.resize((max_width, new_height), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=WEBP_QUALITY)
    return buf.getvalue(), img.width, img.height


# -----------------------------------------------------------------------------
# Tier 1 — PyMuPDF text + color extraction (free)
# -----------------------------------------------------------------------------


def _color_int_to_rgb(color: int) -> tuple[int, int, int]:
    """Decode PyMuPDF span color int into (r, g, b) bytes."""
    return (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF


def _is_green(color: int) -> bool:
    """Green-dominant detection covering common PDF shades (lime, dark green, etc.)."""
    r, g, b = _color_int_to_rgb(color)
    return g >= 120 and g > r * 1.5 and g > b * 1.5


def _is_bold(span: dict) -> bool:
    """PyMuPDF sets bit 4 (value 16) of span['flags'] when the font is bold."""
    return bool(span.get("flags", 0) & (1 << 4))


def _flatten_spans(text_dict: dict) -> list[dict]:
    """Flatten get_text('dict') structure into a list of span dicts sorted top-to-bottom.

    Each returned span has keys: text, color, size, flags, font, bbox (x0, y0, x1, y1).
    """
    spans: list[dict] = []
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # 0 = text block
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "").strip()
                if not text:
                    continue
                spans.append(
                    {
                        "text": text,
                        "color": span.get("color", 0),
                        "size": span.get("size", 0.0),
                        "flags": span.get("flags", 0),
                        "font": span.get("font", ""),
                        "bbox": tuple(span.get("bbox", (0, 0, 0, 0))),
                    }
                )
    spans.sort(key=lambda s: (s["bbox"][1], s["bbox"][0]))
    return spans


def _cluster_into_questions(spans: list[dict]) -> list[list[dict]]:
    """Split spans into per-question clusters using vertical gaps.

    A driving-school slide typically has 1 or 2 questions. We start a new cluster
    whenever the vertical gap between consecutive spans exceeds QUESTION_CLUSTER_GAP_PT.
    """
    if not spans:
        return []

    clusters: list[list[dict]] = [[spans[0]]]
    for span in spans[1:]:
        prev = clusters[-1][-1]
        gap = span["bbox"][1] - prev["bbox"][3]
        if gap > QUESTION_CLUSTER_GAP_PT:
            clusters.append([span])
        else:
            clusters[-1].append(span)
    return clusters


def _parse_question_cluster(cluster: list[dict]) -> tuple[str, list[str], list[int]] | None:
    """Parse one cluster of spans into (question_text, options, correct_indices).

    Heuristics:
        - Options are spans whose text starts with a letter/digit label ("A.", "1)", ...).
        - Everything before the first option span is the question text.
        - An option is marked correct if any of its spans are rendered in green.

    Returns None if the cluster does not look like a question (no options found).
    """
    # Find the first span that looks like an option label.
    first_option_idx: int | None = None
    for i, span in enumerate(cluster):
        if OPTION_LABEL_RE.match(span["text"]):
            first_option_idx = i
            break

    if first_option_idx is None or first_option_idx == 0:
        return None

    question_spans = cluster[:first_option_idx]
    option_spans = cluster[first_option_idx:]

    question_text = " ".join(s["text"] for s in question_spans).strip()
    if len(question_text) < MIN_QUESTION_TEXT_LEN:
        return None

    # Group option spans: a new option starts on each label match.
    options: list[str] = []
    option_is_green: list[bool] = []
    current_text: list[str] = []
    current_green = False
    for span in option_spans:
        if OPTION_LABEL_RE.match(span["text"]):
            if current_text:
                options.append(" ".join(current_text).strip())
                option_is_green.append(current_green)
            current_text = [OPTION_LABEL_RE.sub("", span["text"], count=1)]
            current_green = _is_green(span["color"])
        else:
            current_text.append(span["text"])
            if _is_green(span["color"]):
                current_green = True

    if current_text:
        options.append(" ".join(current_text).strip())
        option_is_green.append(current_green)

    options = [o for o in options if o]
    option_is_green = option_is_green[: len(options)]

    if len(options) < 2:
        return None

    correct_indices = [i for i, is_green in enumerate(option_is_green) if is_green]
    return question_text, options, correct_indices


def _tier1_confidence(
    questions: list[tuple[str, list[str], list[int]]],
    has_image: bool,
    cluster_count: int | None = None,
) -> float:
    """Score how confident we are in the Tier 1 extraction (0.0 - 1.0).

    If cluster_count is provided and exceeds the number of successfully parsed
    questions, the score is halved — this guards against the case where the
    slide has 2 question clusters but only 1 parses cleanly (irregular second
    question). Without the penalty, the "looks perfect" score from the single
    surviving question could keep Tier 1 above the threshold and silently drop
    the second question.
    """
    if not questions:
        return 0.0

    score = 0.0
    # All questions have >= 2 options
    if all(len(opts) >= 2 for _, opts, _ in questions):
        score += 0.3
    # Every question has exactly one correct answer detected via green color
    if all(len(ci) == 1 for _, _, ci in questions):
        score += 0.3
    # Situation image available (embedded or rasterized top region)
    if has_image:
        score += 0.2
    # Question text looks substantive
    if all(len(q) >= MIN_QUESTION_TEXT_LEN for q, _, _ in questions):
        score += 0.1
    # Options within a question have consistent length (not single-char OCR junk)
    if all(all(len(o) >= 2 for o in opts) for _, opts, _ in questions):
        score += 0.1

    # Penalty: if the cluster scanner found more question-shaped blocks than we
    # successfully parsed, halve the score to force a Vision escalation.
    if cluster_count is not None and cluster_count > len(questions):
        score *= 0.5

    return min(score, 1.0)


def _find_largest_embedded_image(
    page: pymupdf.Page, doc: pymupdf.Document
) -> tuple[bytes, int, int, bool] | None:
    """Return ``(png_bytes, width, height, covers_full_page)`` for the largest
    embedded raster image on the page, or ``None`` when the page has none.

    ``covers_full_page`` is ``True`` when the image's placement on the page
    covers at least 85% of the page area — a strong signal that this image
    is a full-slide raster (with question text baked in) rather than a
    standalone illustration photo.
    """
    images = page.get_images(full=True)
    if not images:
        return None

    page_area = max(float(page.rect.width * page.rect.height), 1.0)
    best: tuple[bytes, int, int, bool] | None = None
    best_area = 0
    for img_info in images:
        xref = img_info[0]
        try:
            extracted = doc.extract_image(xref)
        except Exception:
            continue
        width = extracted.get("width", 0)
        height = extracted.get("height", 0)
        area = width * height
        if area <= best_area or not extracted.get("image"):
            continue
        covers_full_page = False
        try:
            bbox = page.get_image_bbox(img_info)
            bbox_area = float(bbox.width * bbox.height)
            covers_full_page = bbox_area / page_area >= 0.85
        except Exception:
            pass
        best = (extracted["image"], width, height, covers_full_page)
        best_area = area
    return best


def _extract_tier1(
    page: pymupdf.Page,
    doc: pymupdf.Document,
    page_number: int,
) -> tuple[list[ExtractedSlideQuestion], float]:
    """Tier 1: extract questions via PyMuPDF text dict + color detection.

    Returns (questions, confidence). An empty list with confidence 0 means this
    page has no extractable text and should escalate to Vision.
    """
    spans = _flatten_spans(page.get_text("dict"))
    if not spans:
        return [], 0.0

    clusters = _cluster_into_questions(spans)
    parsed: list[tuple[str, list[str], list[int]]] = []
    for cluster in clusters:
        result = _parse_question_cluster(cluster)
        if result is not None:
            parsed.append(result)

    if not parsed:
        return [], 0.0

    # Get the situation image: prefer the largest embedded image.
    crop_ratio = _illustration_crop_ratio(page)
    embedded = _find_largest_embedded_image(page, doc)
    if embedded is not None:
        raw_bytes, _, _, covers_full_page = embedded
        if covers_full_page:
            # Embedded image IS the whole slide (text baked in) — crop it.
            webp_bytes, width, height = _crop_to_illustration(
                raw_bytes, crop_ratio=crop_ratio
            )
        else:
            # Already a standalone illustration — keep as-is.
            webp_bytes, width, height = _convert_to_webp(raw_bytes)
        has_image = True
    else:
        # Fall back to rasterizing the whole page and cropping to the
        # illustration region so baked-in question text is dropped (#1669).
        png_bytes = _rasterize_page(page)
        webp_bytes, width, height = _crop_to_illustration(
            png_bytes, crop_ratio=crop_ratio
        )
        has_image = False

    confidence = _tier1_confidence(parsed, has_image, cluster_count=len(clusters))

    questions = [
        ExtractedSlideQuestion(
            question_text=qt,
            options=opts,
            correct_indices=ci,
            explanation=None,  # Tier 1 does not generate explanations
            category=_infer_category(qt, opts),
            page_number=page_number,
            image_bytes=webp_bytes,
            image_width=width,
            image_height=height,
        )
        for qt, opts, ci in parsed
    ]
    return questions, confidence


# -----------------------------------------------------------------------------
# Tier 3 — Claude Vision fallback
# -----------------------------------------------------------------------------


async def _extract_tier3_vision(
    page: pymupdf.Page,
    page_number: int,
    claude: ClaudeService,
) -> list[ExtractedSlideQuestion]:
    """Tier 3: send the rasterized page to Claude Vision and parse the response."""
    png_bytes = _rasterize_page(page)
    # Vision needs the whole slide (question + options text) to read the page;
    # the stored image is cropped to the illustration region so the test-taker
    # doesn't duplicate the question text visually (#1669).
    crop_ratio = _illustration_crop_ratio(page)
    webp_bytes, width, height = _crop_to_illustration(
        png_bytes, crop_ratio=crop_ratio
    )

    b64_image = base64.b64encode(png_bytes).decode("utf-8")
    response = await claude.client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=EXTRACTION_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"Extract questions from this slide (page {page_number}).",
                    },
                ],
            }
        ],
        temperature=0.1,
    )

    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text += block.text

    response_text = response_text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()

    questions_data = json.loads(response_text)
    if not isinstance(questions_data, list):
        questions_data = [questions_data]

    questions: list[ExtractedSlideQuestion] = []
    for q_data in questions_data:
        questions.append(
            ExtractedSlideQuestion(
                question_text=q_data.get("question_text", ""),
                options=q_data.get("options", []),
                correct_indices=q_data.get("correct_indices", []),
                explanation=q_data.get("explanation"),
                category=q_data.get("category"),
                page_number=page_number,
                image_bytes=webp_bytes,
                image_width=width,
                image_height=height,
            )
        )
    return questions


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------


async def extract_questions_from_pdf(
    pdf_path: str | Path,
) -> list[ExtractedSlideQuestion]:
    """Extract MCQ questions from a PDF where each page is a slide.

    Runs Tier 1 (PyMuPDF) first; escalates a page to Tier 3 (Claude Vision) only
    when Tier 1 confidence falls below CONFIDENCE_THRESHOLD or when the page has
    no extractable text. This cuts Vision API calls by ~90% on structured PDFs.
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = pymupdf.open(str(pdf_path))
    all_questions: list[ExtractedSlideQuestion] = []
    stats = ExtractionStats(total_pages=len(doc))

    # Lazy-instantiate the Claude client — only constructed if we actually need Tier 3.
    claude: ClaudeService | None = None

    try:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_number = page_idx + 1

            try:
                tier1_questions, confidence = _extract_tier1(page, doc, page_number)
            except Exception as e:
                logger.warning(
                    "Tier 1 extraction raised, falling back to Vision",
                    page=page_number,
                    error=str(e),
                )
                tier1_questions, confidence = [], 0.0

            if tier1_questions and confidence >= CONFIDENCE_THRESHOLD:
                logger.debug(
                    "Tier 1 accepted",
                    page=page_number,
                    confidence=round(confidence, 2),
                    questions=len(tier1_questions),
                )
                all_questions.extend(tier1_questions)
                stats.tier1_pages += 1
                continue

            logger.info(
                "Escalating to Claude Vision",
                page=page_number,
                tier1_confidence=round(confidence, 2),
                tier1_questions=len(tier1_questions),
            )
            if claude is None:
                claude = ClaudeService()

            try:
                vision_questions = await _extract_tier3_vision(page, page_number, claude)
                all_questions.extend(vision_questions)
                stats.tier3_pages += 1
            except json.JSONDecodeError as e:
                logger.warning(
                    "Failed to parse Claude response for slide",
                    page=page_number,
                    error=str(e),
                )
                stats.failed_pages.append(page_number)
            except Exception as e:
                logger.error(
                    "Failed to process slide",
                    page=page_number,
                    error=str(e),
                )
                stats.failed_pages.append(page_number)
    finally:
        doc.close()

    stats.log(logger)
    return all_questions
