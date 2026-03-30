"""Text chunking service for RAG pipeline.

Splits documents into 512-token chunks with 50-token overlap for optimal embedding and retrieval.
"""

import re
from collections.abc import Generator
from dataclasses import dataclass

import tiktoken


@dataclass
class DocumentChunk:
    """A chunk of text extracted from a source document."""

    content: str
    token_count: int
    chunk_index: int
    source: str
    chapter: str | None = None
    page: int | None = None
    level: int | None = None
    language: str = "en"


class TextChunker:
    """Splits documents into overlapping chunks for RAG pipeline."""

    def __init__(
        self,
        chunk_size: int = 512,
        overlap_size: int = 50,
        encoding_name: str = "cl100k_base",  # GPT-4/text-embedding-3 tokenizer
    ):
        self.chunk_size = chunk_size
        self.overlap_size = overlap_size
        self.encoding = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the specified encoding."""
        return len(self.encoding.encode(text))

    def split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences while preserving sentence boundaries."""
        # Handle French and English sentence endings
        sentence_endings = r"[.!?]+(?:\s|$)"
        sentences = re.split(sentence_endings, text)

        # Clean up and filter empty sentences
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences

    def chunk_document(
        self,
        text: str,
        source: str,
        chapter: str | None = None,
        page: int | None = None,
        level: int | None = None,
        language: str = "en",
    ) -> Generator[DocumentChunk, None, None]:
        """
        Split document into overlapping chunks.

        Args:
            text: The full document text to chunk
            source: Source identifier (e.g., "donaldson", "triola")
            chapter: Chapter identifier if available
            page: Page number if available
            level: Difficulty level (1-4) for targeting
            language: Language code ("fr" or "en")

        Yields:
            DocumentChunk objects with metadata
        """
        if not text.strip():
            return

        # Clean up the text
        text = self._clean_text(text)

        # Split into sentences for better chunk boundaries
        sentences = self.split_into_sentences(text)

        current_chunk = ""
        current_token_count = 0
        chunk_index = 0

        for sentence in sentences:
            sentence_tokens = self.count_tokens(sentence)

            # If adding this sentence would exceed chunk size, finalize current chunk
            if current_token_count + sentence_tokens > self.chunk_size and current_chunk:
                yield DocumentChunk(
                    content=current_chunk.strip(),
                    token_count=current_token_count,
                    chunk_index=chunk_index,
                    source=source,
                    chapter=chapter,
                    page=page,
                    level=level,
                    language=language,
                )

                chunk_index += 1

                # Start new chunk with overlap from previous chunk
                overlap_text = self._get_overlap_text(current_chunk, self.overlap_size)
                current_chunk = overlap_text + " " + sentence
                current_token_count = self.count_tokens(current_chunk)
            else:
                # Add sentence to current chunk
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
                current_token_count += sentence_tokens

        # Yield the final chunk if it has content
        if current_chunk.strip():
            yield DocumentChunk(
                content=current_chunk.strip(),
                token_count=current_token_count,
                chunk_index=chunk_index,
                source=source,
                chapter=chapter,
                page=page,
                level=level,
                language=language,
            )

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text for chunking."""
        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text)

        # Remove page numbers and headers/footers (common patterns)
        text = re.sub(r"\b(?:Page|page)\s*\d+\b", "", text)
        text = re.sub(r"\b\d{1,3}\s*\|\s*Chapter\s*\d+", "", text)

        # Fix common OCR issues in PDFs
        text = re.sub(r"\s*\n\s*", " ", text)  # Normalize line breaks
        text = re.sub(r"([a-z])([A-Z])", r"\1. \2", text)  # Fix missing sentence breaks

        return text.strip()

    def _get_overlap_text(self, text: str, target_tokens: int) -> str:
        """Get the last N tokens worth of text for overlap."""
        if target_tokens <= 0:
            return ""

        # Split into words and work backwards
        words = text.split()
        overlap_words = []
        token_count = 0

        for word in reversed(words):
            word_tokens = self.count_tokens(word)
            if token_count + word_tokens > target_tokens:
                break
            overlap_words.insert(0, word)
            token_count += word_tokens

        return " ".join(overlap_words)


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using PyMuPDF."""
    import fitz  # PyMuPDF

    text_content = []

    try:
        doc = fitz.open(pdf_path)
        for page in doc:
            text = page.get_text()
            if text.strip():
                text_content.append(text)
        doc.close()
    except Exception as e:
        raise ValueError(f"Failed to extract text from {pdf_path}: {e}")

    return "\n".join(text_content)


def detect_language(text: str) -> str:
    """Simple language detection for French vs English."""
    # Common French words that don't appear in English
    french_indicators = [
        "santé",
        "publique",
        "épidémiologie",
        "maladie",
        "population",
        "données",
        "analyse",
        "recherche",
        "étude",
        "résultats",
        "avec",
        "dans",
        "pour",
        "cette",
        "mais",
        "sont",
        "plus",
    ]

    # Count French indicators
    text_lower = text.lower()
    sum(1 for word in french_indicators if word in text_lower)

    # If more than 3 French indicators found in first 1000 chars, likely French
    sample = text_lower[:1000]
    french_in_sample = sum(1 for word in french_indicators if word in sample)

    return "fr" if french_in_sample >= 3 else "en"
