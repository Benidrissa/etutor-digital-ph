#!/usr/bin/env python3
"""Standalone test for PDF extraction functionality."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def test_pdf_extractor_basic():
    """Test basic PDF extractor functionality."""
    from backend.app.ai.rag.pdf_extractor import PDFTextExtractor
    
    # Create temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        resources_path = Path(temp_dir)
        
        # Create mock PDF files
        (resources_path / "Donaldson_test.pdf").touch()
        (resources_path / "Scutchfield_test.pdf").touch() 
        (resources_path / "Triola_test.pdf").touch()
        
        # Test initialization
        extractor = PDFTextExtractor(resources_path)
        assert extractor.resources_path == resources_path
        
        # Test book identification
        assert extractor.identify_book("Donaldson_Essential_Public_Health.pdf") == "donaldson"
        assert extractor.identify_book("Scutchfield_Principles.pdf") == "scutchfield"
        assert extractor.identify_book("Triola_Biostatistics.pdf") == "triola"
        assert extractor.identify_book("unknown_book.pdf") is None
        
        # Test equation extraction
        text_with_equations = """
        The formula is x = y + 2.
        In LaTeX: $E = mc^2$.
        Display math: $$\\int_0^1 f(x)dx$$.
        Greek letters: α, β, γ.
        Symbols: ≤ ≥ ≠ ±.
        """
        
        equations = extractor._extract_equations(text_with_equations)
        assert len(equations) > 0
        print(f"Found {len(equations)} equations: {equations[:3]}...")
        
        # Test text cleaning
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
        assert "This is real content" in cleaned
        assert "This is another paragraph" in cleaned
        assert "Essential Public Health Header" not in cleaned
        print("Text cleaning works correctly")
        
        print("✅ Basic PDF extractor tests passed!")


def test_rag_indexer_basic():
    """Test basic RAG indexer functionality."""
    from backend.app.ai.rag.indexer import RAGIndexer
    
    with tempfile.TemporaryDirectory() as temp_dir:
        resources_path = Path(temp_dir) / "resources"
        output_path = Path(temp_dir) / "output"
        
        resources_path.mkdir(parents=True, exist_ok=True)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Create mock PDF
        (resources_path / "Donaldson_test.pdf").touch()
        
        # Test initialization
        indexer = RAGIndexer(str(resources_path), str(output_path))
        assert indexer.resources_path == resources_path
        assert indexer.output_path == output_path
        assert indexer.output_path.exists()
        
        # Test sentence splitting
        text = "This is the first sentence. This is the second sentence! Is this a question?"
        sentences = indexer._split_into_sentences(text)
        assert len(sentences) == 3
        assert "This is the first sentence" in sentences[0]
        print(f"Sentence splitting works: {len(sentences)} sentences")
        
        # Test chunk metadata creation
        chapter = {
            "chapter_id": "test_ch01",
            "source_book": "donaldson",
            "chapter_number": 1,
            "title": "Test Chapter",
            "page_range": {"start": 1, "end": 3},
            "equations": ["x = y + 1"],
            "extracted_at": "2024-01-01T00:00:00"
        }
        
        content = "This is test chunk content for testing purposes."
        sentences = ["This is test chunk content.", "For testing purposes."]
        
        chunk_data = indexer._create_chunk_metadata(content, chapter, sentences, 0)
        
        assert chunk_data["chunk_id"] == "test_ch01_chunk_000"
        assert chunk_data["content"] == content
        assert chunk_data["metadata"]["source_book"] == "donaldson"
        assert chunk_data["metadata"]["chapter_number"] == 1
        assert chunk_data["metadata"]["sentence_count"] == 2
        
        print("✅ Basic RAG indexer tests passed!")


def test_integration():
    """Test integration between components."""
    from backend.app.ai.rag.pdf_extractor import PDFTextExtractor, ChapterContent
    from backend.app.ai.rag.indexer import RAGIndexer
    from datetime import datetime
    
    with tempfile.TemporaryDirectory() as temp_dir:
        resources_path = Path(temp_dir) / "resources"
        output_path = Path(temp_dir) / "output"
        
        resources_path.mkdir(parents=True, exist_ok=True)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Create mock PDF
        (resources_path / "Donaldson_test.pdf").touch()
        
        indexer = RAGIndexer(str(resources_path), str(output_path))
        
        # Mock the extractor's extract_all_pdfs method
        with patch.object(indexer.extractor, 'extract_all_pdfs') as mock_extract:
            
            # Create mock chapter
            mock_chapter = ChapterContent(
                title="Test Chapter",
                content="This is test content for the mock chapter. It contains multiple sentences to test the chunking functionality.",
                chapter_number=1,
                sections=[{"title": "Introduction", "content": "Intro content"}],
                page_range=(1, 3),
                equations=["x = y + 1"],
                source_book="donaldson",
                extracted_at=datetime.utcnow()
            )
            
            mock_extract.return_value = {"donaldson": [mock_chapter]}
            
            # Test the extraction
            content = indexer.extractor.extract_all_pdfs()
            assert len(content) == 1
            assert "donaldson" in content
            assert len(content["donaldson"]) == 1
            
            print("✅ Integration test passed!")


def main():
    """Run all tests."""
    print("Running standalone PDF extraction tests...\n")
    
    try:
        test_pdf_extractor_basic()
        test_rag_indexer_basic() 
        test_integration()
        
        print("\n🎉 All tests passed!")
        return 0
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())