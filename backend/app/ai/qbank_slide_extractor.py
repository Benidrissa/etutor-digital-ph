"""PDF slide extraction for question bank — extracts image-based MCQs from PDF slides.

Each PDF page is a slide with a traffic situation photo and 1-2 MCQ questions.
Uses PyMuPDF for page rasterization and Claude Vision for structured extraction.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import structlog
from PIL import Image

from app.ai.claude_service import ClaudeService

logger = structlog.get_logger(__name__)

RASTERIZE_DPI = 200
WEBP_MAX_WIDTH = 1024
WEBP_QUALITY = 87

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


async def extract_questions_from_pdf(
    pdf_path: str | Path,
) -> list[ExtractedSlideQuestion]:
    """Extract MCQ questions from a PDF where each page is a slide.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        List of ExtractedSlideQuestion with image bytes and parsed question data
    """
    claude = ClaudeService()
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = pymupdf.open(str(pdf_path))
    all_questions: list[ExtractedSlideQuestion] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_number = page_idx + 1

        logger.info("Processing slide", page=page_number, total=len(doc))

        # Rasterize the full page
        png_bytes = _rasterize_page(page)

        # Convert to WebP for storage
        webp_bytes, width, height = _convert_to_webp(png_bytes)

        # Send to Claude Vision for extraction
        b64_image = base64.b64encode(png_bytes).decode("utf-8")

        try:
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

            # Parse response
            response_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    response_text += block.text

            # Clean up JSON extraction
            response_text = response_text.strip()
            if response_text.startswith("```"):
                response_text = response_text.split("\n", 1)[1]
                if response_text.endswith("```"):
                    response_text = response_text[:-3]
                response_text = response_text.strip()

            questions_data = json.loads(response_text)

            if not isinstance(questions_data, list):
                questions_data = [questions_data]

            for q_data in questions_data:
                all_questions.append(
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

        except json.JSONDecodeError as e:
            logger.warning(
                "Failed to parse Claude response for slide",
                page=page_number,
                error=str(e),
            )
        except Exception as e:
            logger.error(
                "Failed to process slide",
                page=page_number,
                error=str(e),
            )

    doc.close()
    logger.info(
        "PDF extraction complete",
        total_pages=len(doc) if hasattr(doc, "__len__") else "?",
        total_questions=len(all_questions),
    )
    return all_questions
