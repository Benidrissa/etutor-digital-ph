"""Tests for PDF text extraction functionality."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.ai.rag.pdf_extractor import ChapterContent, PDFTextExtractor


class TestPDFTextExtractor:
    """Test cases for PDFTextExtractor."""

    def setup_method(self):
        """Set up test resources."""
        # Create a temporary directory for resources
        self.temp_dir = tempfile.mkdtemp()
        self.resources_path = Path(self.temp_dir)

        # Create mock PDF files
        (self.resources_path / "Donaldson_test.pdf").touch()
        (self.resources_path / "Scutchfield_test.pdf").touch()
        (self.resources_path / "Triola_test.pdf").touch()

    def teardown_method(self):
        """Clean up test resources."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_init(self):
        """Test extractor initialization."""
        extractor = PDFTextExtractor(self.resources_path)
        assert extractor.resources_path == self.resources_path

    def test_init_invalid_path(self):
        """Test initialization with invalid path."""
        with pytest.raises(ValueError, match="Resources path does not exist"):
            PDFTextExtractor("/nonexistent/path")

    def test_identify_book(self):
        """Test book identification from filename."""
        extractor = PDFTextExtractor(self.resources_path)

        assert extractor.identify_book("Donaldson_Essential_Public_Health.pdf") == "donaldson"
        assert extractor.identify_book("Scutchfield_Principles.pdf") == "scutchfield"
        assert extractor.identify_book("Triola_Biostatistics.pdf") == "triola"
        assert extractor.identify_book("unknown_book.pdf") is None

    def test_extract_equations(self):
        """Test equation extraction from text."""
        extractor = PDFTextExtractor(self.resources_path)

        text_with_equations = """
        The formula is x = y + 2.
        In LaTeX: $E = mc^2$.
        Display math: $$\\int_0^1 f(x)dx$$.
        Greek letters: α, β, γ.
        Symbols: ≤ ≥ ≠ ±.
        """

        equations = extractor._extract_equations(text_with_equations)

        # Should find various equation patterns
        assert len(equations) > 0
        assert any("x = y + 2" in eq or "x = y" in eq for eq in equations)
        assert any("$E = mc^2$" in eq for eq in equations)

    def test_clean_text(self):
        """Test text cleaning functionality."""
        extractor = PDFTextExtractor(self.resources_path)

        dirty_text = """
        Essential Public Health Header
        Chapter 1
        This is real content that should be kept.
        This is another paragraph with useful information.
        1
        Chapter 1 Footer
        Essential Public Health Footer
        """

        cleaned = extractor.clean_text(dirty_text, "donaldson")

        # Should remove headers and footers but keep content
        assert "This is real content" in cleaned
        assert "This is another paragraph" in cleaned
        assert "Essential Public Health Header" not in cleaned
        assert "Essential Public Health Footer" not in cleaned

    def test_extract_chapter_title(self):
        """Test chapter title extraction."""
        extractor = PDFTextExtractor(self.resources_path)

        text = """
        Chapter 1: Introduction to Public Health

        This chapter covers the basic concepts...
        """

        import re

        chapter_match = re.search(r"Chapter\s+(\d+)", text)
        title = extractor._extract_chapter_title(text, chapter_match)

        assert "Introduction to Public Health" in title

    def test_extract_sections(self):
        """Test section extraction from chapter text."""
        extractor = PDFTextExtractor(self.resources_path)

        text = """
        INTRODUCTION
        This is the introduction section with detailed content.

        MAIN CONCEPTS
        Here we discuss the main concepts of public health.

        CONCLUSION
        This section summarizes the chapter content.
        """

        sections = extractor._extract_sections(text)

        assert len(sections) == 3
        section_titles = [s["title"] for s in sections]
        assert "INTRODUCTION" in section_titles
        assert "MAIN CONCEPTS" in section_titles
        assert "CONCLUSION" in section_titles

    @patch("pymupdf.open")
    def test_extract_text_from_pdf(self, mock_pymupdf_open):
        """Test PDF text extraction with mocked PyMuPDF."""
        # Mock PyMuPDF document and pages
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Chapter 1\n\nThis is test content with x = y + 1."

        mock_doc.page_count = 1
        mock_doc.load_page.return_value = mock_page
        mock_pymupdf_open.return_value = mock_doc

        # Create actual PDF file for testing
        pdf_path = self.resources_path / "test.pdf"
        pdf_path.touch()

        extractor = PDFTextExtractor(self.resources_path)
        pages = extractor.extract_text_from_pdf(pdf_path)

        assert len(pages) == 1
        assert pages[0]["page_number"] == 1
        assert "Chapter 1" in pages[0]["text"]
        assert len(pages[0]["equations"]) > 0  # Should find "x = y + 1"

    def test_extract_text_from_pdf_file_not_found(self):
        """Test PDF extraction with non-existent file."""
        extractor = PDFTextExtractor(self.resources_path)

        with pytest.raises(FileNotFoundError):
            extractor.extract_text_from_pdf(Path("/nonexistent/file.pdf"))

    @patch("pymupdf.open")
    def test_extract_chapter_structure(self, mock_pymupdf_open):
        """Test chapter structure extraction."""
        # Mock pages with chapter content
        mock_pages = [
            {
                "page_number": 1,
                "text": "Chapter 1: Introduction to Public Health\n\nThis is the first chapter content.",
                "equations": ["x = y + 1"],
                "char_count": 50,
            },
            {
                "page_number": 2,
                "text": "More content for chapter 1.\n\nChapter 2: Epidemiology\n\nSecond chapter starts here.",
                "equations": ["p = n/N"],
                "char_count": 60,
            },
        ]

        extractor = PDFTextExtractor(self.resources_path)
        chapters = extractor.extract_chapter_structure(mock_pages, "donaldson")

        assert len(chapters) == 2
        assert chapters[0].chapter_number == 1
        assert "Introduction to Public Health" in chapters[0].title
        assert chapters[1].chapter_number == 2
        assert "Epidemiology" in chapters[1].title

    def test_finalize_chapter(self):
        """Test chapter finalization."""
        extractor = PDFTextExtractor(self.resources_path)

        chapter_info = {"number": 1, "title": "Test Chapter", "start_page": 1, "end_page": 2}

        pages = [
            {
                "text": "Test content for chapter 1.\nThis is good content.",
                "equations": ["x = y + 1"],
            },
            {"text": "More test content.\nAnother paragraph.", "equations": ["p = n/N"]},
        ]

        chapter = extractor._finalize_chapter(chapter_info, pages, "donaldson")

        assert isinstance(chapter, ChapterContent)
        assert chapter.chapter_number == 1
        assert chapter.title == "Test Chapter"
        assert chapter.source_book == "donaldson"
        assert len(chapter.equations) == 2
        assert chapter.page_range == (1, 2)


class TestRAGIndexer:
    """Test cases for RAGIndexer."""

    def setup_method(self):
        """Set up test resources."""
        self.temp_dir = tempfile.mkdtemp()
        self.resources_path = Path(self.temp_dir) / "resources"
        self.output_path = Path(self.temp_dir) / "output"

        self.resources_path.mkdir(parents=True, exist_ok=True)
        self.output_path.mkdir(parents=True, exist_ok=True)

        # Create mock PDF files
        (self.resources_path / "Donaldson_test.pdf").touch()

    def teardown_method(self):
        """Clean up test resources."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def test_init(self):
        """Test indexer initialization."""
        from app.ai.rag.indexer import RAGIndexer

        indexer = RAGIndexer(str(self.resources_path), str(self.output_path))

        assert indexer.resources_path == self.resources_path
        assert indexer.output_path == self.output_path
        assert indexer.output_path.exists()

    def test_split_into_sentences(self):
        """Test sentence splitting."""
        from app.ai.rag.indexer import RAGIndexer

        indexer = RAGIndexer(str(self.resources_path), str(self.output_path))

        text = "This is the first sentence. This is the second sentence! Is this a question?"
        sentences = indexer._split_into_sentences(text)

        assert len(sentences) == 3
        assert "This is the first sentence" in sentences[0]
        assert "This is the second sentence" in sentences[1]
        assert "Is this a question" in sentences[2]

    def test_create_chunk_metadata(self):
        """Test chunk metadata creation."""
        from app.ai.rag.indexer import RAGIndexer

        indexer = RAGIndexer(str(self.resources_path), str(self.output_path))

        chapter = {
            "chapter_id": "test_ch01",
            "source_book": "donaldson",
            "chapter_number": 1,
            "title": "Test Chapter",
            "page_range": {"start": 1, "end": 3},
            "equations": ["x = y + 1"],
            "extracted_at": "2024-01-01T00:00:00",
        }

        content = "This is test chunk content for testing purposes."
        sentences = ["This is test chunk content.", "For testing purposes."]

        chunk_data = indexer._create_chunk_metadata(content, chapter, sentences, 0)

        assert chunk_data["chunk_id"] == "test_ch01_chunk_000"
        assert chunk_data["content"] == content
        assert chunk_data["metadata"]["source_book"] == "donaldson"
        assert chunk_data["metadata"]["chapter_number"] == 1
        assert chunk_data["metadata"]["sentence_count"] == 2


# Integration test that doesn't actually read PDFs
def test_integration_mock_extraction():
    """Integration test with mocked PDF extraction."""
    with tempfile.TemporaryDirectory() as temp_dir:
        resources_path = Path(temp_dir) / "resources"
        output_path = Path(temp_dir) / "output"

        resources_path.mkdir(parents=True, exist_ok=True)
        output_path.mkdir(parents=True, exist_ok=True)

        # Create mock PDF
        (resources_path / "Donaldson_test.pdf").touch()

        from app.ai.rag.indexer import RAGIndexer

        indexer = RAGIndexer(str(resources_path), str(output_path))

        # Mock the extractor's extract_all_pdfs method
        with patch.object(indexer.extractor, "extract_all_pdfs") as mock_extract:
            from datetime import datetime

            # Create mock chapter
            mock_chapter = ChapterContent(
                title="Test Chapter",
                content="This is test content for the mock chapter.",
                chapter_number=1,
                sections=[{"title": "Introduction", "content": "Intro content"}],
                page_range=(1, 3),
                equations=["x = y + 1"],
                source_book="donaldson",
                extracted_at=datetime.utcnow(),
            )

            mock_extract.return_value = {"donaldson": [mock_chapter]}

            # Test the full pipeline
            content = indexer.extractor.extract_all_pdfs()
            files = []
            for book_id, chapters in content.items():
                output_file = output_path / f"{book_id}_chapters.json"

                import json

                book_data = {
                    "metadata": {
                        "book_id": book_id,
                        "extraction_timestamp": datetime.utcnow().isoformat(),
                        "total_chapters": len(chapters),
                    },
                    "chapters": [],
                }

                with open(output_file, "w") as f:
                    json.dump(book_data, f)

                files.append(output_file)

            # Verify results
            assert len(content) == 1
            assert "donaldson" in content
            assert len(content["donaldson"]) == 1
            assert len(files) == 1
            assert files[0].exists()


if __name__ == "__main__":
    pytest.main([__file__])
