"""Tests for PDF image extraction functionality."""

import io
import struct
import tempfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.rag.image_extractor import (
    BOOKS,
    ExtractedImage,
    PDFImageExtractor,
    _build_figure_patterns,
)


def _make_minimal_png(width: int = 200, height: int = 200) -> bytes:
    """Create a minimal valid PNG for testing."""

    def chunk(name: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + name + data
        crc = zlib.crc32(name + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    signature = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr = chunk(b"IHDR", ihdr_data)
    row = b"\x00" + b"\xff\x00\x00" * width
    raw_data = row * height
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

    def test_identify_book_unknown(self):
        extractor = PDFImageExtractor(self.resources_path)
        assert extractor.identify_book("unknown_book.pdf") is None


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


class TestExtractFigureMetadata:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.extractor = PDFImageExtractor(Path(self.temp_dir))

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir)

    def _make_mock_page(self, blocks: list[dict]) -> MagicMock:
        page = MagicMock()
        page.get_text.return_value = " ".join(
            span["text"]
            for b in blocks
            if b.get("type") == 0
            for line in b.get("lines", [])
            for span in line.get("spans", [])
        )
        page.get_text.side_effect = None
        page.get_text = MagicMock(return_value=page.get_text.return_value)
        page_dict = {"blocks": blocks}
        page.get_text = MagicMock(
            return_value=" ".join(
                span["text"]
                for b in blocks
                if b.get("type") == 0
                for line in b.get("lines", [])
                for span in line.get("spans", [])
            )
        )
        page.get_text.return_value = " ".join(
            span["text"]
            for b in blocks
            if b.get("type") == 0
            for line in b.get("lines", [])
            for span in line.get("spans", [])
        )
        page_dict_mock = MagicMock(return_value=page_dict)
        page.get_text = page_dict_mock
        return page

    def test_extracts_figure_number(self):
        import pymupdf

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
        import pymupdf

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
        import pymupdf

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
        import pymupdf

        page = MagicMock()
        page.get_text.return_value = ""
        page.get_text.side_effect = lambda mode=None: "" if mode != "dict" else {"blocks": []}
        image_bbox = pymupdf.Rect(0, 100, 300, 200)
        result = self.extractor._extract_surrounding_text(page, image_bbox)
        assert isinstance(result, str)

    def test_respects_char_limit(self):
        import pymupdf

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
        mock_page.get_text.return_value = {"blocks": []}
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
        import pymupdf as _pymupdf

        mock_doc = MagicMock()
        mock_doc.page_count = 1
        mock_page = MagicMock()
        mock_page.get_images.return_value = [(42, 0, 200, 200, 8, "CS", "I")]
        mock_page.get_image_info.return_value = [{"xref": 42, "bbox": [10, 10, 210, 210]}]
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
        mock_page.rect = _pymupdf.Rect(0, 0, 612, 792)
        mock_doc.load_page.return_value = mock_page
        mock_open.return_value = mock_doc
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)

        pdf_path = self.resources_path / "Donaldson_test.pdf"
        pdf_path.touch()
        results = self.extractor.extract_images_from_pdf(pdf_path, "donaldson")
        assert len(results) == 1
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
        (self.resources_path / "unknown_file.pdf").touch()
        result = self.extractor.extract_all_pdfs()
        assert "donaldson" in result
        assert "unknown_file" not in result
        mock_extract.assert_called_once()

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
