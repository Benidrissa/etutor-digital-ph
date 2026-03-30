"""PDF text extraction and processing for RAG pipeline.

This module implements the first stage of the RAG pipeline:
- Extract text from reference PDFs using PyMuPDF
- Clean text (remove headers, footers, page numbers)
- Preserve mathematical equations in LaTeX format
- Extract metadata (chapter, section, page)
- Output structured JSON per chapter
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pymupdf  # PyMuPDF


@dataclass
class ExtractedChunk:
    """Represents a chunk of extracted text with metadata."""

    text: str
    source_book: str
    chapter: int | None
    section: str | None
    page_number: int
    has_equations: bool
    metadata: dict[str, str]


@dataclass
class ChapterContent:
    """Represents the complete content of a chapter."""

    title: str
    content: str
    chapter_number: int
    sections: list[dict[str, str]]
    page_range: tuple[int, int]
    equations: list[str]
    source_book: str
    extracted_at: datetime


class PDFTextExtractor:
    """Extract and process text from reference PDFs for RAG indexing."""

    # Book identifiers and their patterns
    BOOKS = {
        "donaldson": {
            "filename_pattern": "Donaldson",
            "chapter_pattern": r"Chapter\s+(\d+)",
            "header_patterns": [r"Essential Public Health.*", r"Fourth Edition.*", r"Donaldson.*"],
            "footer_patterns": [
                r"^\d+$",  # Page numbers
                r"Chapter \d+.*",
                r".*Essential Public Health.*",
            ],
        },
        "scutchfield": {
            "filename_pattern": "Scutchfield",
            "chapter_pattern": r"Chapter\s+(\d+)",
            "header_patterns": [
                r"Principles of Public Health Practice.*",
                r"Scutchfield.*",
                r"Delmar Series.*",
            ],
            "footer_patterns": [r"^\d+$", r"Chapter \d+.*", r".*Principles of Public Health.*"],
        },
        "triola": {
            "filename_pattern": "Triola",
            "chapter_pattern": r"Chapter\s+(\d+)",
            "header_patterns": [r"Biostatistics.*", r"Triola.*", r"Second Edition.*"],
            "footer_patterns": [r"^\d+$", r"Chapter \d+.*", r".*Biostatistics.*"],
            "equation_patterns": [
                r"\$[^$]+\$",  # LaTeX inline math
                r"\$\$[^$]+\$\$",  # LaTeX display math
                r"\\[a-zA-Z]+\{[^}]*\}",  # LaTeX commands
                r"[a-zA-Z]\s*=\s*[^,\n]+",  # Basic equations
            ],
        },
    }

    def __init__(self, resources_path: Path):
        """Initialize extractor with path to resources directory."""
        self.resources_path = Path(resources_path)
        if not self.resources_path.exists():
            raise ValueError(f"Resources path does not exist: {resources_path}")

    def identify_book(self, filename: str) -> str | None:
        """Identify which reference book a PDF file represents."""
        filename_lower = filename.lower()
        for book_id, config in self.BOOKS.items():
            if config["filename_pattern"].lower() in filename_lower:
                return book_id
        return None

    def extract_text_from_pdf(self, pdf_path: Path) -> list[dict]:
        """Extract raw text from PDF with page-level metadata."""
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        pages = []
        doc = pymupdf.open(pdf_path)

        try:
            for page_num in range(doc.page_count):
                page = doc.load_page(page_num)
                text = page.get_text()

                # Extract any mathematical content
                equations = self._extract_equations(text)

                pages.append(
                    {
                        "page_number": page_num + 1,
                        "text": text,
                        "equations": equations,
                        "char_count": len(text),
                    }
                )
        finally:
            doc.close()

        return pages

    def _extract_equations(self, text: str) -> list[str]:
        """Extract mathematical equations from text."""
        equations = []

        # Look for various equation patterns
        patterns = [
            r"\$[^$]+\$",  # LaTeX inline
            r"\$\$[^$]+\$\$",  # LaTeX display
            r"\\[a-zA-Z]+\{[^}]*\}",  # LaTeX commands
            r"[a-zA-Z_]\s*=\s*[^,\n\s]+(?:\s*[+\-*/]\s*[^,\n\s]+)*",  # Basic equations
            r"∑|∏|∫|√|±|≤|≥|≠|α|β|γ|δ|ε|σ|μ|λ|π",  # Mathematical symbols
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.MULTILINE)
            equations.extend(matches)

        return list(set(equations))  # Remove duplicates

    def clean_text(self, text: str, book_id: str) -> str:
        """Clean extracted text by removing headers, footers, and noise."""
        if book_id not in self.BOOKS:
            return text

        config = self.BOOKS[book_id]
        lines = text.split("\n")
        cleaned_lines = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip headers
            is_header = any(
                re.match(pattern, line, re.IGNORECASE) for pattern in config["header_patterns"]
            )
            if is_header:
                continue

            # Skip footers
            is_footer = any(
                re.match(pattern, line, re.IGNORECASE) for pattern in config["footer_patterns"]
            )
            if is_footer:
                continue

            # Skip very short lines that are likely noise
            if len(line) < 10 and not any(char.isdigit() for char in line):
                continue

            cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def extract_chapter_structure(self, pages: list[dict], book_id: str) -> list[ChapterContent]:
        """Extract chapter structure and content from pages."""
        if book_id not in self.BOOKS:
            raise ValueError(f"Unknown book: {book_id}")

        config = self.BOOKS[book_id]
        chapter_pattern = config["chapter_pattern"]
        chapters = []
        current_chapter = None
        current_content = []

        for page_data in pages:
            text = page_data["text"]
            page_num = page_data["page_number"]

            # Look for chapter starts
            chapter_match = re.search(chapter_pattern, text)

            if chapter_match:
                # Save previous chapter if exists
                if current_chapter is not None:
                    chapter_content = self._finalize_chapter(
                        current_chapter, current_content, book_id
                    )
                    chapters.append(chapter_content)

                # Start new chapter
                chapter_num = int(chapter_match.group(1))
                chapter_title = self._extract_chapter_title(text, chapter_match)

                current_chapter = {
                    "number": chapter_num,
                    "title": chapter_title,
                    "start_page": page_num,
                    "end_page": page_num,
                }
                current_content = [page_data]

            elif current_chapter is not None:
                # Continue current chapter
                current_chapter["end_page"] = page_num
                current_content.append(page_data)

        # Don't forget the last chapter
        if current_chapter is not None:
            chapter_content = self._finalize_chapter(current_chapter, current_content, book_id)
            chapters.append(chapter_content)

        return chapters

    def _extract_chapter_title(self, text: str, chapter_match) -> str:
        """Extract chapter title from text around chapter marker."""
        lines = text.split("\n")

        # Find the line with the chapter marker
        chapter_line_idx = None
        for i, line in enumerate(lines):
            if chapter_match.group(0) in line:
                chapter_line_idx = i
                break

        if chapter_line_idx is None:
            return "Unknown Chapter"

        # Look for title in the same line or next few lines
        for i in range(chapter_line_idx, min(chapter_line_idx + 5, len(lines))):
            line = lines[i].strip()

            # Remove chapter number part
            line = re.sub(r"Chapter\s+\d+:?\s*", "", line, flags=re.IGNORECASE)

            # If remaining text is substantial, it's likely the title
            if len(line) > 5 and not line.isdigit():
                return line[:100]  # Truncate very long titles

        return "Unknown Chapter"

    def _finalize_chapter(
        self, chapter_info: dict, pages: list[dict], book_id: str
    ) -> ChapterContent:
        """Create final ChapterContent object from collected data."""
        # Combine all text
        all_text = []
        all_equations = []

        for page_data in pages:
            cleaned_text = self.clean_text(page_data["text"], book_id)
            if cleaned_text.strip():
                all_text.append(cleaned_text)
            all_equations.extend(page_data["equations"])

        combined_text = "\n\n".join(all_text)

        # Extract sections (simple heuristic)
        sections = self._extract_sections(combined_text)

        return ChapterContent(
            title=chapter_info["title"],
            content=combined_text,
            chapter_number=chapter_info["number"],
            sections=sections,
            page_range=(chapter_info["start_page"], chapter_info["end_page"]),
            equations=list(set(all_equations)),
            source_book=book_id,
            extracted_at=datetime.utcnow(),
        )

    def _extract_sections(self, text: str) -> list[dict[str, str]]:
        """Extract section structure from chapter text."""
        sections = []
        lines = text.split("\n")
        current_section = None
        current_content = []

        # Look for section headers (capitalized, short lines)
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Heuristic for section headers: short, mostly caps, no punctuation at end
            is_section_header = (
                len(line) < 80
                and len(line.split()) <= 8
                and line[0].isupper()
                and not line.endswith(".")
                and not line.endswith(",")
                and sum(1 for c in line if c.isupper()) / len(line) > 0.3
            )

            if is_section_header and current_section is not None:
                # Save previous section
                sections.append({"title": current_section, "content": "\n".join(current_content)})
                current_section = line
                current_content = []
            elif is_section_header:
                current_section = line
                current_content = []
            elif current_section is not None:
                current_content.append(line)

        # Don't forget the last section
        if current_section is not None:
            sections.append({"title": current_section, "content": "\n".join(current_content)})

        return sections

    def extract_all_pdfs(self) -> dict[str, list[ChapterContent]]:
        """Extract content from all reference PDFs in resources directory."""
        results = {}

        # Find all PDF files
        pdf_files = list(self.resources_path.glob("*.pdf"))

        if not pdf_files:
            raise ValueError(f"No PDF files found in {self.resources_path}")

        for pdf_path in pdf_files:
            book_id = self.identify_book(pdf_path.name)

            if book_id is None:
                print(f"Warning: Could not identify book for {pdf_path.name}")
                continue

            print(f"Extracting {book_id} from {pdf_path.name}...")

            # Extract pages
            pages = self.extract_text_from_pdf(pdf_path)

            # Extract chapters
            chapters = self.extract_chapter_structure(pages, book_id)

            results[book_id] = chapters
            print(f"Extracted {len(chapters)} chapters from {book_id}")

        return results

    def save_extracted_content(
        self, content: dict[str, list[ChapterContent]], output_path: Path
    ) -> None:
        """Save extracted content to JSON files."""
        output_path.mkdir(parents=True, exist_ok=True)

        for book_id, chapters in content.items():
            book_data = {
                "book_id": book_id,
                "extracted_at": datetime.utcnow().isoformat(),
                "total_chapters": len(chapters),
                "chapters": [],
            }

            for chapter in chapters:
                chapter_data = {
                    "chapter_number": chapter.chapter_number,
                    "title": chapter.title,
                    "content": chapter.content,
                    "sections": chapter.sections,
                    "page_range": chapter.page_range,
                    "equations": chapter.equations,
                    "source_book": chapter.source_book,
                    "extracted_at": chapter.extracted_at.isoformat(),
                    "metadata": {
                        "content_length": len(chapter.content),
                        "section_count": len(chapter.sections),
                        "equation_count": len(chapter.equations),
                        "page_count": chapter.page_range[1] - chapter.page_range[0] + 1,
                    },
                }
                book_data["chapters"].append(chapter_data)

            # Save to file
            output_file = output_path / f"{book_id}_extracted.json"
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(book_data, f, indent=2, ensure_ascii=False)

            print(f"Saved {book_id} content to {output_file}")


def main():
    """CLI entry point for PDF extraction."""
    import sys
    from pathlib import Path

    if len(sys.argv) != 3:
        print("Usage: python pdf_extractor.py <resources_path> <output_path>")
        sys.exit(1)

    resources_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    extractor = PDFTextExtractor(resources_path)

    try:
        # Extract all content
        content = extractor.extract_all_pdfs()

        # Save to JSON
        extractor.save_extracted_content(content, output_path)

        # Print summary
        total_chapters = sum(len(chapters) for chapters in content.values())
        print("\nExtraction complete!")
        print(f"Books processed: {len(content)}")
        print(f"Total chapters: {total_chapters}")

        for book_id, chapters in content.items():
            print(f"  {book_id}: {len(chapters)} chapters")

    except Exception as e:
        print(f"Error during extraction: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
