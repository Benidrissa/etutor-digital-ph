"""PDF image extraction for RAG pipeline.

Extracts images from reference PDFs using PyMuPDF with rich metadata:
- Figure numbers and captions from surrounding text
- Attribution/license information
- Surrounding context text (~500 chars)
- Image type classification (diagram, chart, photo, formula, icon, unknown)
- WebP conversion via Pillow for optimal web delivery
- Vector graphic detection via page.get_drawings() for academic/health PDFs
- Targeted region rasterization (clip to figure bounds) instead of full-page
- FR/EN bilingual figure pattern matching
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf
import structlog

logger = structlog.get_logger(__name__)

# Raised from 100/100/2KB to 200/200/4KB in #2073. PDFs frequently embed
# tiny chapter-opener stock photos and preview thumbnails (100-200px,
# ~3KB) under the same xref table as real figures; `doc.extract_image()`
# returns these binaries verbatim. Real textbook figures rasterize to
# >=200px when extracted at native resolution, so this floor drops the
# placeholders without affecting legitimate diagrams.
MIN_WIDTH_PX = 200
MIN_HEIGHT_PX = 200
MIN_SIZE_BYTES = 4 * 1024
WEBP_MAX_WIDTH = 1024
WEBP_QUALITY = 87
CAPTION_PROXIMITY_PT = 100
SURROUNDING_CHAR_LIMIT = 500
VECTOR_CLUSTER_GAP_PT = 10
VECTOR_MIN_REGION_PX = 100
HIGH_DRAWING_COUNT_THRESHOLD = 2000
RASTERIZE_DPI = 200


@dataclass
class ExtractedImage:
    """Represents an image extracted from a PDF with rich metadata."""

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


# Multi-part numbering pattern: matches "1", "1.5", "2-8", "12.3.4", "1-2-3".
# Mirrors image_linker._FIGURE_RE (#2038). Previous form `(\d+\.?\d*)` only
# matched chapter-and-optional-decimal — it truncated dashed numbering like
# "Figure 2-8" to "Figure 2", which collapsed every chapter-N image into the
# same figure_map key in the linker and was the root cause of the 2/460 link
# rate on legacy courses (#2055).
_NUM = r"(\d+(?:[\.\-]\d+)*)"

BOOKS = {
    "donaldson": {
        "filename_pattern": "Donaldson",
        "figure_patterns": [rf"Figure\s+{_NUM}", rf"Fig\.?\s*{_NUM}"],
        "exhibit_patterns": [],
    },
    "scutchfield": {
        "filename_pattern": "Scutchfield",
        "figure_patterns": [rf"Figure\s+{_NUM}", rf"Fig\.?\s*{_NUM}"],
        "exhibit_patterns": [rf"Exhibit\s+{_NUM}"],
    },
    "triola": {
        "filename_pattern": "Triola",
        "figure_patterns": [rf"Figure\s+{_NUM}", rf"Fig\.?\s*{_NUM}"],
        "exhibit_patterns": [rf"Table\s+{_NUM}", rf"Chart\s+{_NUM}"],
    },
    "generic": {
        "filename_pattern": None,
        "figure_patterns": [
            rf"Figure\s+{_NUM}",
            rf"Fig\.?\s*{_NUM}",
            rf"Sch[eé]ma\s+{_NUM}",
            rf"Tableau\s+{_NUM}",
            rf"Graphique\s+{_NUM}",
            rf"Illustration\s+{_NUM}",
            rf"Diagramme\s+{_NUM}",
            rf"Encadr[eé]\s+{_NUM}",
        ],
        "exhibit_patterns": [
            rf"Table\s+{_NUM}",
            rf"Chart\s+{_NUM}",
            rf"Exhibit\s+{_NUM}",
            rf"Box\s+{_NUM}",
        ],
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

    def identify_book(self, filename: str) -> str:
        filename_lower = filename.lower()
        for book_id, config in BOOKS.items():
            pattern = config.get("filename_pattern")
            if pattern and pattern.lower() in filename_lower:
                return book_id
        return "generic"

    def extract_images_from_pdf(self, pdf_path: Path, source: str) -> list[ExtractedImage]:
        """Extract all qualifying images from a PDF with metadata.

        Args:
            pdf_path: Path to the PDF file.
            source: Source book identifier (e.g. "donaldson", "generic").

        Returns:
            List of ExtractedImage objects; empty list if no images found.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        book_config = BOOKS.get(source, BOOKS["generic"])
        figure_patterns = _build_figure_patterns(book_config)

        results: list[ExtractedImage] = []
        doc = pymupdf.open(pdf_path)

        try:
            for page_idx in range(doc.page_count):
                page = doc.load_page(page_idx)
                page_number = page_idx + 1
                xrefs = page.get_images(full=True)

                already_extracted_bboxes: list[pymupdf.Rect] = []

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
                    already_extracted_bboxes.append(image_bbox)
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

                vector_images = self._extract_non_xref_figures(
                    page, page_number, figure_patterns, already_extracted_bboxes
                )
                results.extend(vector_images)

        finally:
            doc.close()

        results = self._deduplicate_images(results)

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
                for kw in (
                    "diagram",
                    "flowchart",
                    "model",
                    "framework",
                    "process",
                    "pathway",
                    "diagramme",
                    "schéma",
                    "schema",
                    "processus",
                    "modèle",
                    "modele",
                )
            ):
                return "diagram"
            if any(
                kw in caption_lower
                for kw in ("chart", "graph", "table", "plot", "graphique", "tableau", "courbe")
            ):
                return "chart"
            if any(kw in caption_lower for kw in ("formula", "equation", "formule", "équation")):
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
        from PIL import Image, ImageCms

        img = Image.open(io.BytesIO(image_bytes))

        if img.mode == "CMYK":
            icc = img.info.get("icc_profile")
            if icc:
                try:
                    src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
                    dst_profile = ImageCms.createProfile("sRGB")
                    img = ImageCms.profileToProfile(img, src_profile, dst_profile, outputMode="RGB")
                except Exception:
                    img = img.convert("RGB")
            else:
                img = img.convert("RGB")
        elif img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode not in ("RGB",):
            img = img.convert("RGB")

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

    def _detect_vector_figure_regions(
        self,
        page: pymupdf.Page,
        already_extracted_bboxes: list[pymupdf.Rect],
        drawings: list[dict] | None = None,
    ) -> list[pymupdf.Rect]:
        """Detect figure regions composed of vector drawings via clustering.

        Uses union-find to cluster nearby drawing rects into coherent figure regions.
        Returns list of bounding boxes for detected regions, excluding areas already
        covered by extracted raster images.

        Performance cap: returns empty list if drawing count > HIGH_DRAWING_COUNT_THRESHOLD
        (falls back to full-page rasterization in caller).
        """
        if drawings is None:
            drawings = page.get_drawings()
        if not drawings:
            return []

        if len(drawings) > HIGH_DRAWING_COUNT_THRESHOLD:
            return []

        rects = [d["rect"] for d in drawings if d.get("rect")]
        if not rects:
            return []

        parent = list(range(len(rects)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            parent[find(a)] = find(b)

        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                ri, rj = rects[i], rects[j]
                expanded = pymupdf.Rect(
                    ri.x0 - VECTOR_CLUSTER_GAP_PT,
                    ri.y0 - VECTOR_CLUSTER_GAP_PT,
                    ri.x1 + VECTOR_CLUSTER_GAP_PT,
                    ri.y1 + VECTOR_CLUSTER_GAP_PT,
                )
                if expanded.intersects(rj):
                    union(i, j)

        clusters: dict[int, pymupdf.Rect] = {}
        for i, rect in enumerate(rects):
            root = find(i)
            if root not in clusters:
                clusters[root] = pymupdf.Rect(rect)
            else:
                clusters[root] |= rect

        regions: list[pymupdf.Rect] = []
        for cluster_rect in clusters.values():
            if (
                cluster_rect.width < VECTOR_MIN_REGION_PX
                or cluster_rect.height < VECTOR_MIN_REGION_PX
            ):
                continue

            overlaps_existing = any(
                cluster_rect.intersects(existing) for existing in already_extracted_bboxes
            )
            if overlaps_existing:
                continue

            regions.append(cluster_rect)

        return regions

    def _rasterize_region(
        self,
        page: pymupdf.Page,
        clip_rect: pymupdf.Rect,
        dpi: int = RASTERIZE_DPI,
    ) -> tuple[bytes, int, int]:
        """Rasterize a clipped region of a page at the given DPI.

        Adds 15pt padding and intersects with page bounds for clean output.
        Returns (png_bytes, width, height).
        """
        padding = 15
        padded = pymupdf.Rect(
            clip_rect.x0 - padding,
            clip_rect.y0 - padding,
            clip_rect.x1 + padding,
            clip_rect.y1 + padding,
        )
        clipped = padded & page.rect
        pixmap = page.get_pixmap(dpi=dpi, clip=clipped)
        return pixmap.tobytes("png"), pixmap.width, pixmap.height

    def _extract_non_xref_figures(
        self,
        page: pymupdf.Page,
        page_number: int,
        figure_patterns: list[re.Pattern],
        already_extracted_bboxes: list[pymupdf.Rect],
    ) -> list[ExtractedImage]:
        """Extract figures not captured by xref extraction.

        Strategy (in order):
        1. High drawing count (>= HIGH_DRAWING_COUNT_THRESHOLD): full-page rasterize once
        2. Moderate drawings (> 3): detect vector regions, rasterize each with clip
        3. Figure text found but no drawings: full-page rasterize (existing behavior)
        4. Otherwise: skip
        """
        results: list[ExtractedImage] = []

        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []

        drawing_count = len(drawings)

        if drawing_count >= HIGH_DRAWING_COUNT_THRESHOLD:
            extracted = self._rasterize_full_page_as_figure(page, page_number, figure_patterns)
            if extracted:
                results.append(extracted)
            return results

        if drawing_count > 3:
            regions = self._detect_vector_figure_regions(page, already_extracted_bboxes, drawings)
            for region in regions:
                try:
                    png_bytes, w, h = self._rasterize_region(page, region)
                except Exception as exc:
                    logger.warning(
                        "Region rasterization failed",
                        page=page_number,
                        error=str(exc),
                    )
                    continue

                if len(png_bytes) < MIN_SIZE_BYTES or w < MIN_WIDTH_PX or h < MIN_HEIGHT_PX:
                    continue

                try:
                    webp_bytes, final_w, final_h = self._convert_to_webp(
                        png_bytes, "png", max_width=WEBP_MAX_WIDTH
                    )
                except Exception:
                    webp_bytes = png_bytes
                    final_w = w
                    final_h = h

                metadata = self._extract_figure_metadata(page, region, figure_patterns)
                surrounding_text = self._extract_surrounding_text(
                    page, region, SURROUNDING_CHAR_LIMIT
                )
                image_type = self._classify_image_type(metadata.get("caption"), final_w, final_h)

                results.append(
                    ExtractedImage(
                        image_bytes=webp_bytes,
                        width=final_w,
                        height=final_h,
                        original_format="png",
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
            return results

        page_text = page.get_text()
        for pattern in figure_patterns:
            if pattern.search(page_text):
                extracted = self._rasterize_full_page_as_figure(page, page_number, figure_patterns)
                if extracted:
                    results.append(extracted)
                break

        return results

    def _rasterize_full_page_as_figure(
        self,
        page: pymupdf.Page,
        page_number: int,
        figure_patterns: list[re.Pattern],
    ) -> "ExtractedImage | None":
        """Rasterize entire page when it contains figure content (vector or text-referenced)."""
        page_text = page.get_text()
        figure_number: str | None = None
        for pattern in figure_patterns:
            m = pattern.search(page_text)
            if m:
                figure_number = m.group(0).strip()
                break

        try:
            pixmap = page.get_pixmap(dpi=RASTERIZE_DPI)
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
        surrounding_text = self._extract_surrounding_text(page, image_bbox, SURROUNDING_CHAR_LIMIT)
        image_type = self._classify_image_type(metadata.get("caption"), w, h)

        return ExtractedImage(
            image_bytes=webp_bytes,
            width=w,
            height=h,
            original_format="png",
            file_size_bytes=len(webp_bytes),
            page_number=page_number,
            figure_number=figure_number or metadata.get("figure_number"),
            caption=metadata.get("caption"),
            attribution=metadata.get("attribution"),
            image_type=image_type,
            surrounding_text=surrounding_text,
            chapter=metadata.get("chapter"),
            section=metadata.get("section"),
        )

    def _deduplicate_images(self, images: list[ExtractedImage]) -> list[ExtractedImage]:
        """Remove near-duplicate images using average hash (8x8 grayscale, Hamming distance < 5).

        When duplicates found, keeps the higher-resolution one.
        """
        if len(images) <= 1:
            return images

        from PIL import Image

        def avg_hash(img_bytes: bytes) -> int | None:
            try:
                img = Image.open(io.BytesIO(img_bytes)).convert("L").resize((8, 8), Image.LANCZOS)
                pixels = list(img.tobytes())
                avg = sum(pixels) / len(pixels)
                bits = 0
                for px in pixels:
                    bits = (bits << 1) | (1 if px >= avg else 0)
                return bits
            except Exception:
                return None

        def hamming(a: int, b: int) -> int:
            xor = a ^ b
            count = 0
            while xor:
                count += xor & 1
                xor >>= 1
            return count

        hashes: list[int | None] = [avg_hash(img.image_bytes) for img in images]
        keep = [True] * len(images)

        for i in range(len(images)):
            if not keep[i] or hashes[i] is None:
                continue
            for j in range(i + 1, len(images)):
                if not keep[j] or hashes[j] is None:
                    continue
                if hamming(hashes[i], hashes[j]) < 5:
                    area_i = images[i].width * images[i].height
                    area_j = images[j].width * images[j].height
                    if area_i >= area_j:
                        keep[j] = False
                    else:
                        keep[i] = False
                        break

        return [img for img, k in zip(images, keep, strict=True) if k]

    def extract_all_pdfs(self) -> dict[str, list[ExtractedImage]]:
        """Extract images from all PDFs in resources_path.

        Known books (donaldson, scutchfield, triola) are extracted with their
        specific patterns. Unknown PDFs fall back to the "generic" config.
        """
        results: dict[str, list[ExtractedImage]] = {}
        pdf_files = list(self.resources_path.glob("*.pdf"))

        if not pdf_files:
            logger.warning("No PDF files found", path=str(self.resources_path))
            return results

        for pdf_path in pdf_files:
            source = self.identify_book(pdf_path.name)
            images = self.extract_images_from_pdf(pdf_path, source)
            if source in results:
                results[source].extend(images)
            else:
                results[source] = images
            logger.info(
                "Extracted images from PDF",
                source=source,
                pdf=pdf_path.name,
                count=len(images),
            )

        return results
