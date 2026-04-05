"""PDF image extraction for RAG pipeline.

Extracts images from reference PDFs using PyMuPDF with rich metadata:
- Figure numbers and captions from surrounding text
- Attribution/license information
- Surrounding context text (~500 chars)
- Image type classification (diagram, chart, photo, formula, icon, unknown)
- WebP conversion via Pillow for optimal web delivery
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

MIN_WIDTH_PX = 100
MIN_HEIGHT_PX = 100
MIN_SIZE_BYTES = 5 * 1024
WEBP_MAX_WIDTH = 1024
WEBP_QUALITY = 87
CAPTION_PROXIMITY_PT = 50
SURROUNDING_CHAR_LIMIT = 500


@dataclass
class ExtractedImage:
    """Represents an image extracted from a PDF with metadata."""

    image_bytes: bytes
    width: int
    height: int
    original_format: str
    file_size_bytes: int
    page_number: int
    figure_number: str | None
    caption: str | None
    attribution: str | None
    image_type: str
    surrounding_text: str
    chapter: str | None
    section: str | None


BOOKS = {
    "donaldson": {
        "filename_pattern": "Donaldson",
        "figure_patterns": [r"Figure\s+(\d+\.?\d*)", r"Fig\.?\s+(\d+\.?\d*)"],
        "exhibit_patterns": [],
    },
    "scutchfield": {
        "filename_pattern": "Scutchfield",
        "figure_patterns": [r"Figure\s+(\d+\.?\d*)", r"Fig\.?\s+(\d+\.?\d*)"],
        "exhibit_patterns": [r"Exhibit\s+(\d+\.?\d*)"],
    },
    "triola": {
        "filename_pattern": "Triola",
        "figure_patterns": [r"Figure\s+(\d+\.?\d*)", r"Fig\.?\s+(\d+\.?\d*)"],
        "exhibit_patterns": [r"Table\s+(\d+[\-\.]?\d*)", r"Chart\s+(\d+\.?\d*)"],
    },
}

_ATTRIBUTION_PATTERNS = [
    r"(?i)(credit\s*[:=]\s*[^\n]+)",
    r"(?i)(attribution\s*[:=]\s*[^\n]+)",
    r"(?i)(CC\s+BY[^\n]*)",
    r"(?i)(license\s*[:=]\s*[^\n]+)",
    r"(?i)(source\s*[:=]\s*[^\n]+)",
    r"(?i)(©\s*[^\n]+)",
]


def _build_figure_patterns(book_config: dict) -> list[re.Pattern]:
    all_patterns = book_config.get("figure_patterns", []) + book_config.get("exhibit_patterns", [])
    if not all_patterns:
        all_patterns = [r"Figure\s+(\d+\.?\d*)", r"Fig\.?\s+(\d+\.?\d*)"]
    return [re.compile(p, re.IGNORECASE) for p in all_patterns]


class PDFImageExtractor:
    """Extract images from reference PDFs with rich metadata for RAG integration."""

    def __init__(self, resources_path: Path):
        self.resources_path = Path(resources_path)
        if not self.resources_path.exists():
            raise ValueError(f"Resources path does not exist: {resources_path}")

    def identify_book(self, filename: str) -> str | None:
        filename_lower = filename.lower()
        for book_id, config in BOOKS.items():
            if config["filename_pattern"].lower() in filename_lower:
                return book_id
        return None

    def extract_images_from_pdf(self, pdf_path: Path, source: str) -> list[ExtractedImage]:
        """Extract all qualifying images from a PDF with metadata.

        Args:
            pdf_path: Path to the PDF file.
            source: Source book identifier (e.g. "donaldson").

        Returns:
            List of ExtractedImage objects; empty list if no images found.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        book_config = BOOKS.get(source, BOOKS["donaldson"])
        figure_patterns = _build_figure_patterns(book_config)

        results: list[ExtractedImage] = []
        doc = pymupdf.open(pdf_path)

        try:
            for page_idx in range(doc.page_count):
                page = doc.load_page(page_idx)
                page_number = page_idx + 1
                xrefs = page.get_images(full=True)

                if not xrefs:
                    extracted = self._try_rasterize_figure(doc, page, page_number, figure_patterns)
                    if extracted:
                        results.append(extracted)
                    continue

                for xref_info in xrefs:
                    xref = xref_info[0]
                    try:
                        raw = doc.extract_image(xref)
                    except Exception as exc:
                        logger.warning(
                            "Failed to extract image xref",
                            page=page_number,
                            xref=xref,
                            error=str(exc),
                        )
                        continue

                    if not raw:
                        continue

                    img_bytes: bytes = raw["image"]
                    original_format: str = raw.get("ext", "png").lower()
                    orig_width: int = raw.get("width", 0)
                    orig_height: int = raw.get("height", 0)
                    orig_size: int = len(img_bytes)

                    if (
                        orig_width < MIN_WIDTH_PX
                        or orig_height < MIN_HEIGHT_PX
                        or orig_size < MIN_SIZE_BYTES
                    ):
                        continue

                    image_bbox = self._get_image_bbox(page, xref)
                    metadata = self._extract_figure_metadata(page, image_bbox, figure_patterns)
                    surrounding_text = self._extract_surrounding_text(
                        page, image_bbox, SURROUNDING_CHAR_LIMIT
                    )
                    image_type = self._classify_image_type(
                        metadata.get("caption"), orig_width, orig_height
                    )

                    try:
                        webp_bytes, final_width, final_height = self._convert_to_webp(
                            img_bytes, original_format, max_width=WEBP_MAX_WIDTH
                        )
                    except Exception as exc:
                        logger.warning(
                            "WebP conversion failed, using original",
                            page=page_number,
                            error=str(exc),
                        )
                        webp_bytes = img_bytes
                        final_width = orig_width
                        final_height = orig_height

                    results.append(
                        ExtractedImage(
                            image_bytes=webp_bytes,
                            width=final_width,
                            height=final_height,
                            original_format=original_format,
                            file_size_bytes=len(webp_bytes),
                            page_number=page_number,
                            figure_number=metadata.get("figure_number"),
                            caption=metadata.get("caption"),
                            attribution=metadata.get("attribution"),
                            image_type=image_type,
                            surrounding_text=surrounding_text,
                            chapter=metadata.get("chapter"),
                            section=metadata.get("section"),
                        )
                    )

        finally:
            doc.close()

        logger.info(
            "Image extraction complete",
            source=source,
            pdf=str(pdf_path),
            count=len(results),
        )
        return results

    def _get_image_bbox(self, page: pymupdf.Page, xref: int) -> pymupdf.Rect:
        """Return the bounding box of an image on a page by its xref."""
        for img_info in page.get_image_info(xrefs=True):
            if img_info.get("xref") == xref:
                bbox = img_info.get("bbox")
                if bbox:
                    return pymupdf.Rect(bbox)
        return page.rect

    def _extract_figure_metadata(
        self,
        page: pymupdf.Page,
        image_bbox: pymupdf.Rect,
        figure_patterns: list[re.Pattern],
    ) -> dict:
        """Extract figure number, caption, and attribution from text near image bbox."""
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        text_blocks: list[tuple[float, str]] = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            block_bbox = pymupdf.Rect(block["bbox"])
            block_text = " ".join(
                span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
            ).strip()
            if not block_text:
                continue
            vertical_dist = min(
                abs(block_bbox.y0 - image_bbox.y1),
                abs(block_bbox.y1 - image_bbox.y0),
            )
            text_blocks.append((vertical_dist, block_text))

        nearby: list[str] = [
            text
            for dist, text in sorted(text_blocks, key=lambda x: x[0])
            if dist <= CAPTION_PROXIMITY_PT
        ]

        figure_number: str | None = None
        caption: str | None = None
        attribution: str | None = None
        chapter: str | None = None
        section: str | None = None

        combined_nearby = " ".join(nearby)

        for pattern in figure_patterns:
            m = pattern.search(combined_nearby)
            if m:
                figure_number = m.group(0).strip()
                caption_start = m.end()
                rest = combined_nearby[caption_start:].lstrip(" .:–—-").strip()
                if rest:
                    sentence_match = re.search(r"[.!?]", rest)
                    if sentence_match and sentence_match.start() > 0:
                        caption = rest[: sentence_match.start() + 1].strip()
                    else:
                        caption = rest[:150].strip()
                break

        for attr_pattern in _ATTRIBUTION_PATTERNS:
            m = re.search(attr_pattern, combined_nearby)
            if m:
                attribution = m.group(1).strip()
                break

        ch_match = re.search(r"(?i)chapter\s+(\d+)[:\s–-]*([^\n]{0,80})", combined_nearby)
        if ch_match:
            chapter = ch_match.group(0).strip()

        return {
            "figure_number": figure_number,
            "caption": caption,
            "attribution": attribution,
            "chapter": chapter,
            "section": section,
        }

    def _classify_image_type(self, caption: str | None, width: int, height: int) -> str:
        """Classify image type based on caption keywords and dimensions."""
        if caption:
            caption_lower = caption.lower()
            if any(
                kw in caption_lower
                for kw in ("diagram", "flowchart", "model", "framework", "process", "pathway")
            ):
                return "diagram"
            if any(kw in caption_lower for kw in ("chart", "graph", "table", "plot")):
                return "chart"
            if any(kw in caption_lower for kw in ("formula", "equation")):
                return "formula"

        if width < 150 or height < 150:
            return "icon"

        if width > 400 and height > 300:
            return "photo"

        return "unknown"

    def _convert_to_webp(
        self,
        image_bytes: bytes,
        original_format: str,
        max_width: int = WEBP_MAX_WIDTH,
    ) -> tuple[bytes, int, int]:
        """Convert image bytes to WebP, capping width at max_width."""
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background

        if img.width > max_width:
            ratio = max_width / img.width
            new_height = max(1, int(img.height * ratio))
            img = img.resize((max_width, new_height), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="WEBP", quality=WEBP_QUALITY)
        return buf.getvalue(), img.width, img.height

    def _extract_surrounding_text(
        self,
        page: pymupdf.Page,
        image_bbox: pymupdf.Rect,
        char_limit: int = SURROUNDING_CHAR_LIMIT,
    ) -> str:
        """Extract up to char_limit chars of text surrounding the image bbox."""
        full_text = page.get_text()
        if not full_text:
            return ""

        half = char_limit // 2

        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        before_texts: list[str] = []
        after_texts: list[str] = []

        for block in blocks:
            if block.get("type") != 0:
                continue
            block_bbox = pymupdf.Rect(block["bbox"])
            block_text = " ".join(
                span["text"] for line in block.get("lines", []) for span in line.get("spans", [])
            ).strip()
            if not block_text:
                continue

            if block_bbox.y1 <= image_bbox.y0:
                before_texts.append(block_text)
            elif block_bbox.y0 >= image_bbox.y1:
                after_texts.append(block_text)

        before = " ".join(before_texts)[-half:]
        after = " ".join(after_texts)[:half]
        return (before + " " + after).strip()[:char_limit]

    def _try_rasterize_figure(
        self,
        doc: pymupdf.Document,
        page: pymupdf.Page,
        page_number: int,
        figure_patterns: list[re.Pattern],
    ) -> ExtractedImage | None:
        """Rasterize a page region when a figure reference exists but no image xref found."""
        page_text = page.get_text()
        for pattern in figure_patterns:
            m = pattern.search(page_text)
            if not m:
                continue

            figure_number = m.group(0).strip()
            try:
                pixmap = page.get_pixmap(dpi=150)
                png_bytes = pixmap.tobytes("png")
            except Exception as exc:
                logger.warning("Rasterization failed", page=page_number, error=str(exc))
                return None

            if len(png_bytes) < MIN_SIZE_BYTES:
                return None

            try:
                webp_bytes, w, h = self._convert_to_webp(png_bytes, "png", max_width=WEBP_MAX_WIDTH)
            except Exception:
                webp_bytes = png_bytes
                w = pixmap.width
                h = pixmap.height

            image_bbox = page.rect
            metadata = self._extract_figure_metadata(page, image_bbox, figure_patterns)
            surrounding_text = self._extract_surrounding_text(
                page, image_bbox, SURROUNDING_CHAR_LIMIT
            )
            image_type = self._classify_image_type(metadata.get("caption"), w, h)

            return ExtractedImage(
                image_bytes=webp_bytes,
                width=w,
                height=h,
                original_format="png",
                file_size_bytes=len(webp_bytes),
                page_number=page_number,
                figure_number=figure_number,
                caption=metadata.get("caption"),
                attribution=metadata.get("attribution"),
                image_type=image_type,
                surrounding_text=surrounding_text,
                chapter=metadata.get("chapter"),
                section=metadata.get("section"),
            )

        return None

    def extract_all_pdfs(self) -> dict[str, list[ExtractedImage]]:
        """Extract images from all recognized PDFs in resources_path."""
        results: dict[str, list[ExtractedImage]] = {}
        pdf_files = list(self.resources_path.glob("*.pdf"))

        if not pdf_files:
            logger.warning("No PDF files found", path=str(self.resources_path))
            return results

        for pdf_path in pdf_files:
            source = self.identify_book(pdf_path.name)
            if source is None:
                logger.warning("Could not identify book", filename=pdf_path.name)
                continue

            images = self.extract_images_from_pdf(pdf_path, source)
            results[source] = images
            logger.info(
                "Extracted images from book",
                source=source,
                count=len(images),
            )

        return results
