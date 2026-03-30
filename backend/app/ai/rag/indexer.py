"""RAG indexer service for managing PDF content extraction and preparation for embedding.

This service coordinates the first phase of the RAG pipeline:
- Extract text from reference PDFs
- Prepare content for chunking and embedding
- Manage extracted content storage
"""

import json
from datetime import datetime
from pathlib import Path

from .pdf_extractor import ChapterContent, PDFTextExtractor


class RAGIndexer:
    """Service for managing PDF extraction and indexing preparation."""

    def __init__(self, resources_path: str, output_path: str):
        """Initialize the indexer.

        Args:
            resources_path: Path to directory containing reference PDFs
            output_path: Path where extracted content will be stored
        """
        self.resources_path = Path(resources_path)
        self.output_path = Path(output_path)
        self.extractor = PDFTextExtractor(self.resources_path)

        # Ensure output directory exists
        self.output_path.mkdir(parents=True, exist_ok=True)

    async def extract_all_content(self) -> dict[str, list[ChapterContent]]:
        """Extract content from all reference PDFs.

        Returns:
            Dictionary mapping book IDs to their extracted chapters
        """
        return self.extractor.extract_all_pdfs()

    async def save_extracted_content(self, content: dict[str, list[ChapterContent]]) -> list[Path]:
        """Save extracted content to JSON files.

        Args:
            content: Extracted content by book

        Returns:
            List of paths to created JSON files
        """
        created_files = []

        for book_id, chapters in content.items():
            output_file = self.output_path / f"{book_id}_chapters.json"

            book_data = {
                "metadata": {
                    "book_id": book_id,
                    "extraction_timestamp": datetime.utcnow().isoformat(),
                    "total_chapters": len(chapters),
                    "extractor_version": "1.0.0",
                },
                "chapters": [
                    {
                        "chapter_id": f"{book_id}_ch{chapter.chapter_number:02d}",
                        "chapter_number": chapter.chapter_number,
                        "title": chapter.title,
                        "content": chapter.content,
                        "sections": chapter.sections,
                        "page_range": {
                            "start": chapter.page_range[0],
                            "end": chapter.page_range[1],
                        },
                        "equations": chapter.equations,
                        "source_book": chapter.source_book,
                        "extracted_at": chapter.extracted_at.isoformat(),
                        "statistics": {
                            "content_length": len(chapter.content),
                            "section_count": len(chapter.sections),
                            "equation_count": len(chapter.equations),
                            "page_count": chapter.page_range[1] - chapter.page_range[0] + 1,
                        },
                    }
                    for chapter in chapters
                ],
            }

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(book_data, f, indent=2, ensure_ascii=False)

            created_files.append(output_file)

        return created_files

    def load_extracted_content(self, book_id: str | None = None) -> dict[str, list[dict]]:
        """Load previously extracted content from JSON files.

        Args:
            book_id: Optional specific book to load. If None, loads all books.

        Returns:
            Dictionary mapping book IDs to their chapter data
        """
        content = {}

        if book_id:
            json_files = [self.output_path / f"{book_id}_chapters.json"]
        else:
            json_files = list(self.output_path.glob("*_chapters.json"))

        for json_file in json_files:
            if not json_file.exists():
                continue

            with open(json_file, encoding="utf-8") as f:
                book_data = json.load(f)

            extracted_book_id = book_data["metadata"]["book_id"]
            content[extracted_book_id] = book_data["chapters"]

        return content

    def get_content_statistics(self) -> dict[str, dict]:
        """Get statistics about extracted content.

        Returns:
            Statistics for each book and overall totals
        """
        content = self.load_extracted_content()
        statistics = {}

        total_chapters = 0
        total_pages = 0
        total_equations = 0
        total_content_length = 0

        for book_id, chapters in content.items():
            book_stats = {
                "chapter_count": len(chapters),
                "total_pages": 0,
                "total_equations": 0,
                "total_content_length": 0,
                "chapters": [],
            }

            for chapter in chapters:
                stats = chapter["statistics"]
                book_stats["total_pages"] += stats["page_count"]
                book_stats["total_equations"] += stats["equation_count"]
                book_stats["total_content_length"] += stats["content_length"]

                book_stats["chapters"].append(
                    {
                        "chapter_number": chapter["chapter_number"],
                        "title": chapter["title"],
                        "pages": stats["page_count"],
                        "sections": stats["section_count"],
                        "equations": stats["equation_count"],
                        "content_length": stats["content_length"],
                    }
                )

            statistics[book_id] = book_stats

            total_chapters += book_stats["chapter_count"]
            total_pages += book_stats["total_pages"]
            total_equations += book_stats["total_equations"]
            total_content_length += book_stats["total_content_length"]

        statistics["_totals"] = {
            "books": len(content),
            "chapters": total_chapters,
            "pages": total_pages,
            "equations": total_equations,
            "content_length": total_content_length,
        }

        return statistics

    def prepare_chunks_for_embedding(
        self, max_chunk_size: int = 512, overlap: int = 64
    ) -> list[dict]:
        """Prepare text chunks for embedding generation.

        Args:
            max_chunk_size: Maximum tokens per chunk (approximate)
            overlap: Token overlap between chunks

        Returns:
            List of chunks ready for embedding
        """
        content = self.load_extracted_content()
        chunks = []

        for _book_id, chapters in content.items():
            for chapter in chapters:
                chapter_chunks = self._chunk_chapter_content(chapter, max_chunk_size, overlap)
                chunks.extend(chapter_chunks)

        return chunks

    def _chunk_chapter_content(
        self, chapter: dict, max_chunk_size: int, overlap: int
    ) -> list[dict]:
        """Split chapter content into chunks for embedding.

        Args:
            chapter: Chapter data from JSON
            max_chunk_size: Max tokens per chunk
            overlap: Overlap between chunks

        Returns:
            List of chunk dictionaries
        """
        chunks = []
        content = chapter["content"]

        # Simple approximation: 1 token ≈ 4 characters
        max_chars = max_chunk_size * 4

        # Split content into sentences for better chunk boundaries
        sentences = self._split_into_sentences(content)

        current_chunk = ""
        current_sentences = []

        for sentence in sentences:
            # Check if adding this sentence would exceed the limit
            potential_chunk = current_chunk + " " + sentence if current_chunk else sentence

            if len(potential_chunk) <= max_chars:
                current_chunk = potential_chunk
                current_sentences.append(sentence)
            else:
                # Save current chunk if it has content
                if current_chunk:
                    chunk_data = self._create_chunk_metadata(
                        current_chunk, chapter, current_sentences, len(chunks)
                    )
                    chunks.append(chunk_data)

                # Start new chunk with overlap
                if overlap > 0 and current_sentences:
                    # Include some sentences from previous chunk for overlap
                    overlap_sentences = (
                        current_sentences[-2:] if len(current_sentences) > 1 else current_sentences
                    )
                    current_chunk = " ".join(overlap_sentences) + " " + sentence
                    current_sentences = overlap_sentences + [sentence]
                else:
                    current_chunk = sentence
                    current_sentences = [sentence]

        # Don't forget the last chunk
        if current_chunk:
            chunk_data = self._create_chunk_metadata(
                current_chunk, chapter, current_sentences, len(chunks)
            )
            chunks.append(chunk_data)

        return chunks

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences using simple heuristics."""
        import re

        # Split on sentence endings, but be careful with abbreviations
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)

        # Clean up sentences
        cleaned = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence and len(sentence) > 10:  # Skip very short fragments
                cleaned.append(sentence)

        return cleaned

    def _create_chunk_metadata(
        self, content: str, chapter: dict, sentences: list[str], chunk_index: int
    ) -> dict:
        """Create metadata for a text chunk.

        Args:
            content: The chunk text content
            chapter: Parent chapter data
            sentences: Sentences in this chunk
            chunk_index: Index of chunk within chapter

        Returns:
            Chunk dictionary with metadata
        """
        return {
            "chunk_id": f"{chapter['chapter_id']}_chunk_{chunk_index:03d}",
            "content": content,
            "metadata": {
                "source_book": chapter["source_book"],
                "chapter_number": chapter["chapter_number"],
                "chapter_title": chapter["title"],
                "chapter_id": chapter["chapter_id"],
                "page_range": chapter["page_range"],
                "chunk_index": chunk_index,
                "sentence_count": len(sentences),
                "character_count": len(content),
                "contains_equations": any(eq in content for eq in chapter["equations"]),
                "extracted_at": chapter["extracted_at"],
            },
        }
