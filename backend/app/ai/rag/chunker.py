"""Text chunking service for RAG pipeline.

Splits documents into 512-token chunks with 50-token overlap for optimal embedding and retrieval.
"""

import re
from collections.abc import Generator
from dataclasses import dataclass
from uuid import UUID

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
    course_resource_id: UUID | None = None


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

    _ABBREV_RE = re.compile(
        r"\b(?:Fig|fig|Ch|ch|Vol|vol|No|no|Dr|dr|Mr|mr|Mrs|mrs|vs|al|eg|pp|etc|approx|est)\."
    )
    _DECIMAL_RE = re.compile(r"\d\.\d")
    _SENTENCE_END_RE = re.compile(r"[.!?]+(?:\s|$)")

    def split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences while preserving sentence boundaries."""
        placeholder = "\x00"

        protected = self._ABBREV_RE.sub(lambda m: m.group().replace(".", placeholder), text)
        protected = self._DECIMAL_RE.sub(lambda m: m.group().replace(".", placeholder), protected)

        parts = self._SENTENCE_END_RE.split(protected)

        sentences = [s.replace(placeholder, ".").strip() for s in parts if s.strip()]
        return sentences

    def chunk_document(
        self,
        text: str,
        source: str,
        chapter: str | None = None,
        page: int | None = None,
        level: int | None = None,
        language: str = "en",
        course_resource_id: UUID | None = None,
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
            course_resource_id: FK back to ``course_resources.id`` so the
                citation formatter can resolve a chunk to its originating
                PDF without fingerprint matching (#2186).

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

            if sentence_tokens > self.chunk_size:
                sub_sentences = self._split_by_tokens(sentence, self.chunk_size)
                for sub in sub_sentences:
                    sub_tokens = self.count_tokens(sub)
                    if current_token_count + sub_tokens > self.chunk_size and current_chunk:
                        yield DocumentChunk(
                            content=current_chunk.strip(),
                            token_count=current_token_count,
                            chunk_index=chunk_index,
                            source=source,
                            chapter=chapter,
                            page=page,
                            level=level,
                            language=language,
                            course_resource_id=course_resource_id,
                        )
                        chunk_index += 1
                        overlap_text = self._get_overlap_text(current_chunk, self.overlap_size)
                        current_chunk = overlap_text + " " + sub
                        current_token_count = self.count_tokens(current_chunk)
                    else:
                        if current_chunk:
                            current_chunk += " " + sub
                        else:
                            current_chunk = sub
                        current_token_count += sub_tokens
                continue

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
                    course_resource_id=course_resource_id,
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
                course_resource_id=course_resource_id,
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

    def _split_by_tokens(self, text: str, max_tokens: int) -> list[str]:
        """Split text into segments of at most max_tokens using tiktoken."""
        tokens = self.encoding.encode(text)
        segments = []
        for i in range(0, len(tokens), max_tokens):
            segment = self.encoding.decode(tokens[i : i + max_tokens])
            segments.append(segment)
        return segments

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


def extract_pages_from_pdf(pdf_path: str) -> list[tuple[int, str]]:
    """Extract text from a PDF as a list of `(page_number, text)` tuples.

    Page numbers are 1-indexed. Empty pages are skipped (returned list is
    sparse on page numbers, never sparse on indices). Used by the chunker
    so each `DocumentChunk.page` reflects the source page — the linker's
    contextual matching is dead without this (#2038).
    """
    import fitz  # PyMuPDF

    pages: list[tuple[int, str]] = []
    try:
        doc = fitz.open(pdf_path)
        for idx, page in enumerate(doc):
            text = page.get_text()
            if text and text.strip():
                pages.append((idx + 1, text))
        doc.close()
    except Exception as e:
        raise ValueError(f"Failed to extract text from {pdf_path}: {e}")
    return pages


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract text from PDF using PyMuPDF. Joins pages with newlines.

    Kept as a thin wrapper around `extract_pages_from_pdf` for callers
    that don't care about page boundaries.
    """
    return "\n".join(text for _, text in extract_pages_from_pdf(pdf_path))


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
