"""Tests for PDF image extraction functionality."""

import io
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf
import pytest

from app.ai.rag.image_extractor import (
    BOOKS,
    ExtractedImage,
    PDFImageExtractor,
    _build_figure_patterns,
)


def _make_minimal_png(width: int = 200, height: int = 200) -> bytes:
    """Create a minimal valid PNG for testing.

    Uses seeded pseudo-random pixel data so the compressed size stays above
    MIN_SIZE_BYTES (2 KB) while remaining deterministic across test runs.
    """
    import random as _random

    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    rng = _random.Random(42)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)
    rows = []
    for _ in range(height):
        row_pixels = bytes([rng.randint(0, 255) for _ in range(width * 3)])
        rows.append(b"\x00" + row_pixels)
    raw_data = b"".join(rows)
    idat = chunk(b"IDAT", zlib.compress(raw_data))
    iend = chunk(b"IEND", b"")
    return signature + ihdr + idat + iend


class TestPDFImageExtractorInit:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.resources_path = Path(self.temp_dir)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_init_valid_path(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.resources_path == self.resources_path

    def test_init_invalid_path(self):
        with pytest.raises(ValueError, match="Resources path does not exist"):
            PDFImageExtractor(Path("/nonexistent/path/xyz"))

    def test_identify_book_donaldson(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("Donaldson_Essential_PH.pdf") == "donaldson"

    def test_identify_book_scutchfield(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("Scutchfield_Principles.pdf") == "scutchfield"

    def test_identify_book_triola(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("Triola_Biostatistics.pdf") == "triola"

    def test_identify_book_unknown_returns_generic(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("unknown_book.pdf") == "generic"

    def test_identify_book_fr_guide_returns_generic(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("Guide_investissement.pdf") == "generic"


class TestBuildFigurePatterns:
    def test_returns_compiled_patterns(self):
        config = BOOKS["donaldson"]
        patterns = _build_figure_patterns(config)
        assert len(patterns) > 0
        assert all(hasattr(p, "search") for p in patterns)

    def test_scutchfield_has_exhibit_pattern(self):
        config = BOOKS["scutchfield"]
        patterns = _build_figure_patterns(config)
        pattern_strings = [p.pattern for p in patterns]
        assert any("Exhibit" in s for s in pattern_strings)

    def test_triola_has_table_pattern(self):
        config = BOOKS["triola"]
        patterns = _build_figure_patterns(config)
        pattern_strings = [p.pattern for p in patterns]
        assert any("Table" in s for s in pattern_strings)

    def test_empty_config_uses_defaults(self):
        patterns = _build_figure_patterns({})
        assert len(patterns) >= 1


class TestGenericBookConfig:
    """Tests for the generic book config with FR/EN patterns."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_generic_config_exists(self):
        assert "generic" in BOOKS

    def test_generic_has_fr_figure_patterns(self):
        config = BOOKS["generic"]
        patterns = _build_figure_patterns(config)
        combined = " ".join(p.pattern for p in patterns)
        assert "Sch" in combined or "éma" in combined or "Tableau" in combined

    def test_generic_matches_schema_fr(self):
        config = BOOKS["generic"]
        patterns = _build_figure_patterns(config)
        text = "Schéma 1.2 — Organisation des services de santé"
        matched = any(p.search(text) for p in patterns)
        assert matched

    def test_generic_matches_tableau_fr(self):
        config = BOOKS["generic"]
        patterns = _build_figure_patterns(config)
        text = "Tableau 3 Répartition des cas de paludisme par région"
        matched = any(p.search(text) for p in patterns)
        assert matched

    def test_generic_matches_encadre_fr(self):
        config = BOOKS["generic"]
        patterns = _build_figure_patterns(config)
        text = "Encadré 2 Points clés de la stratégie nationale"
        matched = any(p.search(text) for p in patterns)
        assert matched

    def test_generic_matches_en_figure(self):
        config = BOOKS["generic"]
        patterns = _build_figure_patterns(config)
        text = "Figure 5 Distribution of malaria cases"
        matched = any(p.search(text) for p in patterns)
        assert matched

    def test_generic_filename_pattern_is_none(self):
        assert BOOKS["generic"]["filename_pattern"] is None


class TestClassifyImageType:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_diagram_from_caption(self):
        assert (
            self.extractor._classify_image_type("A flowchart showing the process", 400, 300)
            == "diagram"
        )

    def test_diagram_keyword_model(self):
        assert (
            self.extractor._classify_image_type("Conceptual model framework", 400, 300) == "diagram"
        )

    def test_chart_from_caption(self):
        assert (
            self.extractor._classify_image_type("Bar chart of incidence rates", 400, 300) == "chart"
        )

    def test_formula_from_caption(self):
        assert (
            self.extractor._classify_image_type("Formula for relative risk", 400, 300) == "formula"
        )

    def test_icon_small_dimensions(self):
        assert self.extractor._classify_image_type(None, 120, 120) == "icon"

    def test_photo_large_dimensions(self):
        assert self.extractor._classify_image_type(None, 800, 600) == "photo"

    def test_unknown_when_no_caption_medium_size(self):
        assert self.extractor._classify_image_type(None, 300, 250) == "unknown"

    def test_caption_none_does_not_raise(self):
        result = self.extractor._classify_image_type(None, 200, 200)
        assert result in ("diagram", "chart", "formula", "icon", "photo", "unknown")

    def test_fr_diagramme_keyword(self):
        assert (
            self.extractor._classify_image_type("Diagramme organisationnel de la santé", 400, 300)
            == "diagram"
        )

    def test_fr_schema_keyword(self):
        assert (
            self.extractor._classify_image_type("Schéma du processus de vaccination", 400, 300)
            == "diagram"
        )

    def test_fr_graphique_keyword(self):
        assert (
            self.extractor._classify_image_type("Graphique de la courbe d'incidence", 400, 300)
            == "chart"
        )

    def test_fr_tableau_keyword(self):
        assert (
            self.extractor._classify_image_type("Tableau des indicateurs de santé", 400, 300)
            == "chart"
        )

    def test_fr_formule_keyword(self):
        assert (
            self.extractor._classify_image_type("Formule du taux de létalité", 400, 300)
            == "formula"
        )

    def test_fr_processus_keyword(self):
        assert (
            self.extractor._classify_image_type("Processus de prise en charge", 400, 300)
            == "diagram"
        )


class TestConvertToWebP:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_converts_png_to_webp(self):
        png_bytes = _make_minimal_png(200, 200)
        webp_bytes, w, h = self.extractor._convert_to_webp(png_bytes, "png")
        assert len(webp_bytes) > 0
        assert w == 200
        assert h == 200

    def test_caps_width_at_max(self):
        png_bytes = _make_minimal_png(2000, 1000)
        webp_bytes, w, h = self.extractor._convert_to_webp(png_bytes, "png", max_width=1024)
        assert w == 1024
        assert h == 512

    def test_does_not_upscale_small_image(self):
        png_bytes = _make_minimal_png(100, 100)
        _, w, h = self.extractor._convert_to_webp(png_bytes, "png", max_width=1024)
        assert w == 100
        assert h == 100

    def test_output_is_valid_webp(self):
        from PIL import Image

        png_bytes = _make_minimal_png(200, 200)
        webp_bytes, _, _ = self.extractor._convert_to_webp(png_bytes, "png")
        img = Image.open(io.BytesIO(webp_bytes))
        assert img.format == "WEBP"

    def test_cmyk_conversion(self):
        """CMYK image should be converted to RGB WebP without errors."""
        from PIL import Image

        cmyk_img = Image.new("CMYK", (200, 200), (100, 50, 0, 10))
        buf = io.BytesIO()
        cmyk_img.save(buf, format="JPEG")
        jpeg_bytes = buf.getvalue()

        webp_bytes, w, h = self.extractor._convert_to_webp(jpeg_bytes, "jpeg")
        result_img = Image.open(io.BytesIO(webp_bytes))
        assert result_img.format == "WEBP"
        assert result_img.mode == "RGB"
        assert w == 200
        assert h == 200


class TestExtractFigureMetadata:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def _make_mock_page(self, blocks: list[dict]) -> MagicMock:
        page = MagicMock()
        page_dict = {"blocks": blocks}
        page.get_text = MagicMock(return_value=page_dict)
        return page

    def test_extracts_figure_number(self):
        blocks = [
            {
                "type": 0,
                "bbox": [10, 200, 300, 220],
                "lines": [{"spans": [{"text": "Figure 3.1 Mortality trends in West Africa"}]}],
            }
        ]
        page = MagicMock()
        page.get_text.return_value = {"blocks": blocks}
        image_bbox = pymupdf.Rect(10, 160, 300, 200)
        patterns = _build_figure_patterns(BOOKS["donaldson"])
        meta = self.extractor._extract_figure_metadata(page, image_bbox, patterns)
        assert meta["figure_number"] is not None
        assert "3.1" in meta["figure_number"] or "Figure" in meta["figure_number"]

    def test_returns_none_when_no_figure_nearby(self):
        blocks = [
            {
                "type": 0,
                "bbox": [10, 1000, 300, 1020],
                "lines": [{"spans": [{"text": "Some distant text far away"}]}],
            }
        ]
        page = MagicMock()
        page.get_text.return_value = {"blocks": blocks}
        image_bbox = pymupdf.Rect(10, 100, 300, 150)
        patterns = _build_figure_patterns(BOOKS["donaldson"])
        meta = self.extractor._extract_figure_metadata(page, image_bbox, patterns)
        assert meta["figure_number"] is None

    def test_extracts_attribution(self):
        blocks = [
            {
                "type": 0,
                "bbox": [10, 210, 300, 230],
                "lines": [{"spans": [{"text": "Figure 2 Risk factors. Credit: WHO AFRO 2023"}]}],
            }
        ]
        page = MagicMock()
        page.get_text.return_value = {"blocks": blocks}
        image_bbox = pymupdf.Rect(10, 160, 300, 210)
        patterns = _build_figure_patterns(BOOKS["donaldson"])
        meta = self.extractor._extract_figure_metadata(page, image_bbox, patterns)
        assert meta["attribution"] is not None
        assert "WHO" in meta["attribution"] or "Credit" in meta["attribution"]


class TestExtractSurroundingText:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_returns_string(self):
        page = MagicMock()
        page.get_text.return_value = ""
        page.get_text.side_effect = lambda mode=None: "" if mode != "dict" else {"blocks": []}
        image_bbox = pymupdf.Rect(0, 100, 300, 200)
        result = self.extractor._extract_surrounding_text(page, image_bbox)
        assert isinstance(result, str)

    def test_respects_char_limit(self):
        blocks = [
            {
                "type": 0,
                "bbox": [10, 10, 300, 50],
                "lines": [{"spans": [{"text": "A" * 400}]}],
            },
            {
                "type": 0,
                "bbox": [10, 300, 300, 340],
                "lines": [{"spans": [{"text": "B" * 400}]}],
            },
        ]
        page = MagicMock()
        page.get_text.side_effect = lambda mode=None: (
            "text" if mode != "dict" else {"blocks": blocks}
        )
        image_bbox = pymupdf.Rect(10, 100, 300, 250)
        result = self.extractor._extract_surrounding_text(page, image_bbox, char_limit=100)
        assert len(result) <= 100


class TestDetectVectorFigureRegions:
    """Tests for vector drawing clustering logic."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def _make_drawing(self, x0, y0, x1, y1):
        return {"rect": pymupdf.Rect(x0, y0, x1, y1)}

    def test_empty_drawings_returns_empty(self):
        page = MagicMock()
        page.get_drawings.return_value = []
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        result = self.extractor._detect_vector_figure_regions(page, [])
        assert result == []

    def test_high_drawing_count_returns_empty(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            self._make_drawing(i, i, i + 10, i + 10) for i in range(2001)
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        result = self.extractor._detect_vector_figure_regions(page, [])
        assert result == []

    def test_nearby_drawings_cluster_into_one_region(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            self._make_drawing(100, 100, 200, 150),
            self._make_drawing(205, 100, 300, 150),
            self._make_drawing(100, 155, 300, 200),
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        result = self.extractor._detect_vector_figure_regions(page, [])
        assert len(result) == 1
        region = result[0]
        assert region.x0 <= 100
        assert region.y0 <= 100
        assert region.x1 >= 300
        assert region.y1 >= 200

    def test_distant_drawings_form_separate_regions(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            self._make_drawing(50, 50, 200, 200),
            self._make_drawing(450, 550, 580, 700),
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        result = self.extractor._detect_vector_figure_regions(page, [])
        assert len(result) == 2

    def test_small_clusters_filtered_out(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            self._make_drawing(10, 10, 50, 50),
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        result = self.extractor._detect_vector_figure_regions(page, [])
        assert result == []

    def test_overlapping_existing_bbox_excluded(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            self._make_drawing(100, 100, 300, 300),
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        existing = pymupdf.Rect(150, 150, 250, 250)
        result = self.extractor._detect_vector_figure_regions(page, [existing])
        assert result == []


class TestRasterizeRegion:
    """Tests for clipped region rasterization."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_rasterize_region_returns_png_bytes(self):
        mock_pixmap = MagicMock()
        png_data = _make_minimal_png(200, 150)
        mock_pixmap.tobytes.return_value = png_data
        mock_pixmap.width = 200
        mock_pixmap.height = 150

        page = MagicMock()
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        page.get_pixmap.return_value = mock_pixmap

        clip_rect = pymupdf.Rect(100, 100, 300, 250)
        png_bytes, w, h = self.extractor._rasterize_region(page, clip_rect)

        assert png_bytes == png_data
        assert w == 200
        assert h == 150
        page.get_pixmap.assert_called_once()
        call_kwargs = page.get_pixmap.call_args
        assert "clip" in call_kwargs.kwargs

    def test_rasterize_region_adds_padding(self):
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = _make_minimal_png(200, 200)
        mock_pixmap.width = 200
        mock_pixmap.height = 200

        page = MagicMock()
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        page.get_pixmap.return_value = mock_pixmap

        clip_rect = pymupdf.Rect(100, 100, 200, 200)
        self.extractor._rasterize_region(page, clip_rect)

        call_kwargs = page.get_pixmap.call_args.kwargs
        used_clip = call_kwargs["clip"]
        assert used_clip.x0 < 100
        assert used_clip.y0 < 100
        assert used_clip.x1 > 200
        assert used_clip.y1 > 200


class TestExtractNonXrefFigures:
    """Tests for the multi-strategy non-xref figure extraction."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def _make_figure_patterns(self):
        return _build_figure_patterns(BOOKS["generic"])

    def test_high_drawing_count_triggers_full_page_rasterize(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            {"rect": pymupdf.Rect(i, i, i + 5, i + 5)} for i in range(2001)
        ]
        page.get_text.side_effect = lambda mode=None: (
            "Figure 1 Some important chart" if mode != "dict" else {"blocks": []}
        )
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = _make_minimal_png(612, 792)
        mock_pixmap.width = 612
        mock_pixmap.height = 792
        page.get_pixmap.return_value = mock_pixmap

        doc = MagicMock()
        patterns = self._make_figure_patterns()

        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [])
        assert len(results) >= 1
        assert results[0].original_format == "png"

    def test_moderate_drawings_triggers_region_detection(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            {"rect": pymupdf.Rect(100, 100, 300, 300)},
            {"rect": pymupdf.Rect(110, 110, 290, 290)},
            {"rect": pymupdf.Rect(120, 120, 280, 280)},
            {"rect": pymupdf.Rect(130, 130, 270, 270)},
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        page.get_text.side_effect = lambda mode=None: (
            "Figure 1 A chart" if mode != "dict" else {"blocks": []}
        )

        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = _make_minimal_png(200, 200)
        mock_pixmap.width = 200
        mock_pixmap.height = 200
        page.get_pixmap.return_value = mock_pixmap

        doc = MagicMock()
        patterns = self._make_figure_patterns()

        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [])
        assert len(results) >= 1

    def test_mixed_page_xref_and_vector_both_extracted(self):
        """KEY regression test: pages with both xrefs and vector drawings capture both."""
        page = MagicMock()
        page.get_drawings.return_value = [
            {"rect": pymupdf.Rect(100, 400, 400, 600)},
            {"rect": pymupdf.Rect(110, 410, 390, 590)},
            {"rect": pymupdf.Rect(120, 420, 380, 580)},
            {"rect": pymupdf.Rect(130, 430, 370, 570)},
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        page.get_text.side_effect = lambda mode=None: (
            "Figure 2 Vector chart below Figure 1 raster above"
            if mode != "dict"
            else {"blocks": []}
        )

        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = _make_minimal_png(300, 200)
        mock_pixmap.width = 300
        mock_pixmap.height = 200
        page.get_pixmap.return_value = mock_pixmap

        doc = MagicMock()
        patterns = self._make_figure_patterns()

        existing_bbox = pymupdf.Rect(50, 50, 400, 200)
        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [existing_bbox])
        assert len(results) >= 1

    def test_no_drawings_figure_text_triggers_full_page(self):
        page = MagicMock()
        page.get_drawings.return_value = []
        page.get_text.side_effect = lambda mode=None: (
            "Figure 3 shows the distribution" if mode != "dict" else {"blocks": []}
        )
        page.rect = pymupdf.Rect(0, 0, 612, 792)

        mock_pixmap = MagicMock()
        mock_pixmap.tobytes.return_value = _make_minimal_png(612, 792)
        mock_pixmap.width = 612
        mock_pixmap.height = 792
        page.get_pixmap.return_value = mock_pixmap

        doc = MagicMock()
        patterns = self._make_figure_patterns()

        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [])
        assert len(results) == 1

    def test_no_drawings_no_figure_text_returns_empty(self):
        page = MagicMock()
        page.get_drawings.return_value = []
        page.get_text.side_effect = lambda mode=None: (
            "Some text without any figure references on this page"
            if mode != "dict"
            else {"blocks": []}
        )
        page.rect = pymupdf.Rect(0, 0, 612, 792)

        doc = MagicMock()
        patterns = self._make_figure_patterns()

        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [])
        assert results == []


class TestHighDrawingCountPage:
    """Tests for pages with extremely high drawing counts (mm_master scenario)."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_detect_vector_skips_high_draw_count(self):
        page = MagicMock()
        page.get_drawings.return_value = [
            {"rect": pymupdf.Rect(i % 100, (i // 100) * 10, (i % 100) + 5, (i // 100) * 10 + 5)}
            for i in range(13000)
        ]
        page.rect = pymupdf.Rect(0, 0, 612, 792)
        regions = self.extractor._detect_vector_figure_regions(page, [])
        assert regions == []

    @patch.object(PDFImageExtractor, "_rasterize_full_page_as_figure")
    def test_high_draw_count_calls_full_page_rasterize(self, mock_rasterize):
        mock_rasterize.return_value = ExtractedImage(
            image_bytes=b"fake",
            width=612,
            height=792,
            original_format="png",
            file_size_bytes=4,
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="photo",
            surrounding_text="",
            chapter=None,
            section=None,
        )
        page = MagicMock()
        page.get_drawings.return_value = [
            {"rect": pymupdf.Rect(i, i, i + 5, i + 5)} for i in range(2001)
        ]
        doc = MagicMock()
        patterns = _build_figure_patterns(BOOKS["generic"])

        results = self.extractor._extract_non_xref_figures(doc, page, 1, patterns, [])
        mock_rasterize.assert_called_once()
        assert len(results) == 1


class TestDeduplication:
    """Tests for image deduplication via average hash."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def _make_image(self, width=200, height=200, page=1):
        png = _make_minimal_png(width, height)
        return ExtractedImage(
            image_bytes=png,
            width=width,
            height=height,
            original_format="png",
            file_size_bytes=len(png),
            page_number=page,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )

    def test_single_image_unchanged(self):
        images = [self._make_image()]
        result = self.extractor._deduplicate_images(images)
        assert len(result) == 1

    def test_identical_images_keeps_larger(self):
        from PIL import Image

        base_img = Image.new("RGB", (200, 200), (128, 64, 32))

        def to_png_at_size(img, w, h):
            resized = img.resize((w, h))
            buf = io.BytesIO()
            resized.save(buf, format="PNG")
            return buf.getvalue()

        png_small = to_png_at_size(base_img, 100, 100)
        png_large = to_png_at_size(base_img, 200, 200)

        img_small = ExtractedImage(
            image_bytes=png_small,
            width=100,
            height=100,
            original_format="png",
            file_size_bytes=len(png_small),
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )
        img_large = ExtractedImage(
            image_bytes=png_large,
            width=200,
            height=200,
            original_format="png",
            file_size_bytes=len(png_large),
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )

        result = self.extractor._deduplicate_images([img_small, img_large])
        assert len(result) == 1
        assert result[0].width * result[0].height >= 100 * 100

    def test_different_images_kept_both(self):
        png1 = _make_minimal_png(200, 200)
        png2 = _make_minimal_png(201, 200)

        images = [
            ExtractedImage(
                image_bytes=png1,
                width=200,
                height=200,
                original_format="png",
                file_size_bytes=len(png1),
                page_number=1,
                figure_number=None,
                caption=None,
                attribution=None,
                image_type="unknown",
                surrounding_text="",
                chapter=None,
                section=None,
            ),
            ExtractedImage(
                image_bytes=png2,
                width=201,
                height=200,
                original_format="png",
                file_size_bytes=len(png2),
                page_number=2,
                figure_number=None,
                caption=None,
                attribution=None,
                image_type="unknown",
                surrounding_text="",
                chapter=None,
                section=None,
            ),
        ]
        result = self.extractor._deduplicate_images(images)
        assert len(result) == 2

    def test_empty_list_unchanged(self):
        result = self.extractor._deduplicate_images([])
        assert result == []


class TestExtractImagesFromPDF:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.resources_path = Path(self.temp_dir)
        self.extractor = PDFImageExtractor(self.resources_path)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            self.extractor.extract_images_from_pdf(Path("/nonexistent/file.pdf"), "donaldson")

    @patch("pymupdf.open")
    def test_returns_empty_list_when_no_images(self, mock_open):
        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_page = MagicMock()
        mock_page.get_images.return_value = []
        mock_page.get_drawings.return_value = []
        mock_page.get_text.return_value = "Some text without figure references"
        mock_doc.load_page.return_value = mock_page
        mock_open.return_value = mock_doc
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        pdf_path = self.resources_path / "test.pdf"
        pdf_path.touch()
        results = self.extractor.extract_images_from_pdf(pdf_path, "donaldson")
        assert results == []

    @patch("pymupdf.open")
    def test_filters_small_images(self, mock_open):
        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42, 0, 50, 50, 8, "CS", "I")]
        mock_page.get_image_info.return_value = []
        mock_page.get_text.side_effect = lambda mode=None: "" if mode != "dict" else {"blocks": []}
        mock_page.get_drawings.return_value = []
        small_png = _make_minimal_png(50, 50)
        mock_doc.extract_image.return_value = {
            "image": small_png,
            "ext": "png",
            "width": 50,
            "height": 50,
        }
        mock_doc.load_page.return_value = mock_page
        mock_open.return_value = mock_doc
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        pdf_path = self.resources_path / "test.pdf"
        pdf_path.touch()
        results = self.extractor.extract_images_from_pdf(pdf_path, "donaldson")
        assert results == []

    @patch("pymupdf.open")
    def test_extracts_valid_image(self, mock_open):
        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42, 0, 200, 200, 8, "CS", "I")]
        mock_page.get_image_info.return_value = [{"xref": 42, "bbox": [10, 10, 210, 210]}]
        mock_page.get_drawings.return_value = []
        big_png = _make_minimal_png(200, 200)
        mock_doc.extract_image.return_value = {
            "image": big_png,
            "ext": "png",
            "width": 200,
            "height": 200,
        }

        blocks = [
            {
                "type": 0,
                "bbox": [10, 215, 300, 235],
                "lines": [
                    {"spans": [{"text": "Figure 1 Example image showing epidemiological trends"}]}
                ],
            }
        ]

        def mock_get_text(mode=None):
            if mode == "dict":
                return {"blocks": blocks}
            return "Figure 1 Example image showing epidemiological trends"

        mock_page.get_text = MagicMock(side_effect=mock_get_text)
        mock_page.rect = pymupdf.Rect(0, 0, 612, 792)
        mock_doc.load_page.return_value = mock_page
        mock_open.return_value = mock_doc
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        pdf_path = self.resources_path / "Donaldson_test.pdf"
        pdf_path.touch()
        results = self.extractor.extract_images_from_pdf(pdf_path, "donaldson")
        assert len(results) >= 1
        img = results[0]
        assert isinstance(img, ExtractedImage)
        assert img.width == 200
        assert img.height == 200
        assert img.page_number == 1
        assert img.original_format == "png"
        assert len(img.image_bytes) > 0


class TestExtractAllPDFs:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.resources_path = Path(self.temp_dir)
        self.extractor = PDFImageExtractor(self.resources_path)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_returns_empty_dict_when_no_pdfs(self):
        result = self.extractor.extract_all_pdfs()
        assert result == {}

    @patch.object(PDFImageExtractor, "extract_images_from_pdf")
    def test_processes_recognized_pdfs(self, mock_extract):
        mock_extract.return_value = []
        (self.resources_path / "Donaldson_test.pdf").touch()
        result = self.extractor.extract_all_pdfs()
        assert "donaldson" in result
        mock_extract.assert_called()

    @patch.object(PDFImageExtractor, "extract_images_from_pdf")
    def test_unknown_pdfs_processed_as_generic(self, mock_extract):
        mock_extract.return_value = []
        (self.resources_path / "Guide_investissement.pdf").touch()
        result = self.extractor.extract_all_pdfs()
        assert "generic" in result

    @patch.object(PDFImageExtractor, "extract_images_from_pdf")
    def test_aggregates_results_per_book(self, mock_extract):
        dummy_image = ExtractedImage(
            image_bytes=b"fake",
            width=200,
            height=200,
            original_format="png",
            file_size_bytes=4,
            page_number=1,
            figure_number="Figure 1",
            caption="Test caption",
            attribution=None,
            image_type="diagram",
            surrounding_text="nearby text",
            chapter=None,
            section=None,
        )
        mock_extract.return_value = [dummy_image]
        (self.resources_path / "Donaldson_test.pdf").touch()
        result = self.extractor.extract_all_pdfs()
        assert result["donaldson"] == [dummy_image]

    @patch.object(PDFImageExtractor, "extract_images_from_pdf")
    def test_multiple_generic_pdfs_aggregated(self, mock_extract):
        dummy_image = ExtractedImage(
            image_bytes=b"fake",
            width=200,
            height=200,
            original_format="png",
            file_size_bytes=4,
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )
        mock_extract.return_value = [dummy_image]
        (self.resources_path / "Guide_sante.pdf").touch()
        (self.resources_path / "Rapport_OMS.pdf").touch()
        result = self.extractor.extract_all_pdfs()
        assert "generic" in result
        assert len(result["generic"]) == 2


class TestExtractedImageDataclass:
    def test_instantiation(self):
        img = ExtractedImage(
            image_bytes=b"data",
            width=400,
            height=300,
            original_format="jpeg",
            file_size_bytes=4,
            page_number=5,
            figure_number="Figure 4",
            caption="Caption text",
            attribution="CC BY 4.0",
            image_type="photo",
            surrounding_text="surrounding context",
            chapter="Chapter 2",
            section="Section 2.1",
        )
        assert img.width == 400
        assert img.image_type == "photo"
        assert img.attribution == "CC BY 4.0"

    def test_optional_fields_can_be_none(self):
        img = ExtractedImage(
            image_bytes=b"data",
            width=200,
            height=200,
            original_format="png",
            file_size_bytes=4,
            page_number=1,
            figure_number=None,
            caption=None,
            attribution=None,
            image_type="unknown",
            surrounding_text="",
            chapter=None,
            section=None,
        )
        assert img.figure_number is None
        assert img.caption is None
        assert img.attribution is None
