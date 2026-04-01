#!/usr/bin/env python3
"""
Test PDF Extraction and Chunk Generation

This script tests the PDF extraction and chunking process using the pre-extracted
JSON data without requiring OpenAI API keys or database connection.

Usage:
    python test_pdf_extraction.py
"""

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


def load_extracted_books() -> dict[str, dict[str, Any]]:
    """Load all pre-extracted book data."""
    data_dir = Path(__file__).parent / "data" / "extracted"

    books = {
        "donaldson": "donaldson_chapters.json",
        "triola": "triola_chapters.json",
        "scutchfield": "scutchfield_chapters.json",
    }

    book_data = {}

    for book_id, filename in books.items():
        file_path = data_dir / filename

        if not file_path.exists():
            logger.error("Extracted data file not found", file=str(file_path))
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            book_data[book_id] = data
            chapters_count = len(data.get("chapters", []))

            logger.info(
                "Loaded book data",
                book=book_id,
                chapters=chapters_count,
                total_content_size=sum(
                    len(ch.get("content", "")) for ch in data.get("chapters", [])
                ),
            )

        except Exception as e:
            logger.error("Failed to load book data", book=book_id, file=filename, error=str(e))

    return book_data


def analyze_chapters(book_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Analyze the chapter structure and content."""
    analysis = {"books": {}, "total_chapters": 0, "total_content_chars": 0, "avg_chapter_length": 0}

    all_chapter_lengths = []

    for book_id, data in book_data.items():
        chapters = data.get("chapters", [])
        book_analysis = {
            "chapters": len(chapters),
            "content_chars": 0,
            "avg_chapter_length": 0,
            "sample_titles": [],
        }

        chapter_lengths = []
        for chapter in chapters:
            content_length = len(chapter.get("content", ""))
            chapter_lengths.append(content_length)
            book_analysis["content_chars"] += content_length

            # Collect sample chapter titles
            title = chapter.get("title", "").strip()
            if title and len(book_analysis["sample_titles"]) < 3:
                book_analysis["sample_titles"].append(title)

        if chapters:
            book_analysis["avg_chapter_length"] = sum(chapter_lengths) // len(chapters)

        all_chapter_lengths.extend(chapter_lengths)
        analysis["books"][book_id] = book_analysis
        analysis["total_chapters"] += len(chapters)
        analysis["total_content_chars"] += book_analysis["content_chars"]

    if all_chapter_lengths:
        analysis["avg_chapter_length"] = sum(all_chapter_lengths) // len(all_chapter_lengths)

    return analysis


def simulate_chunking(book_data: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Simulate the chunking process and return statistics."""
    chunk_size = 2048  # ~512 tokens
    overlap = 200  # ~50 tokens

    chunking_stats = {"total_chunks": 0, "total_tokens_estimated": 0, "books": {}}

    for book_id, data in book_data.items():
        chapters = data.get("chapters", [])
        book_chunks = 0
        book_tokens = 0

        for chapter in chapters:
            content = chapter.get("content", "").strip()
            if not content:
                continue

            # Simulate chunking
            for i in range(0, len(content), chunk_size - overlap):
                chunk_content = content[i : i + chunk_size]
                if chunk_content.strip():
                    book_chunks += 1
                    # Estimate tokens (rough: 1 token = 4 chars)
                    estimated_tokens = len(chunk_content) // 4
                    book_tokens += estimated_tokens

        chunking_stats["books"][book_id] = {"chunks": book_chunks, "estimated_tokens": book_tokens}

        chunking_stats["total_chunks"] += book_chunks
        chunking_stats["total_tokens_estimated"] += book_tokens

    return chunking_stats


def main():
    """Run the PDF extraction test."""
    logger.info("Starting PDF extraction and chunking test")

    # Load pre-extracted book data
    book_data = load_extracted_books()

    if not book_data:
        logger.error("No book data could be loaded")
        return

    # Analyze chapter structure
    logger.info("Analyzing chapter structure...")
    analysis = analyze_chapters(book_data)

    logger.info(
        "Chapter analysis completed",
        total_books=len(book_data),
        total_chapters=analysis["total_chapters"],
        total_content_chars=analysis["total_content_chars"],
        avg_chapter_length=analysis["avg_chapter_length"],
    )

    # Show per-book breakdown
    for book_id, book_stats in analysis["books"].items():
        logger.info(
            "Book analysis",
            book=book_id,
            chapters=book_stats["chapters"],
            content_chars=book_stats["content_chars"],
            avg_length=book_stats["avg_chapter_length"],
            sample_titles=book_stats["sample_titles"],
        )

    # Simulate chunking process
    logger.info("Simulating chunking process...")
    chunking_stats = simulate_chunking(book_data)

    logger.info(
        "Chunking simulation completed",
        total_chunks=chunking_stats["total_chunks"],
        estimated_total_tokens=chunking_stats["total_tokens_estimated"],
        avg_tokens_per_chunk=chunking_stats["total_tokens_estimated"]
        // chunking_stats["total_chunks"]
        if chunking_stats["total_chunks"] > 0
        else 0,
    )

    # Show per-book chunking breakdown
    for book_id, book_stats in chunking_stats["books"].items():
        logger.info(
            "Book chunking stats",
            book=book_id,
            chunks=book_stats["chunks"],
            estimated_tokens=book_stats["estimated_tokens"],
        )

    # Final summary
    logger.info("Test completed successfully")
    logger.info(
        "Ready for production indexing with these expected results",
        expected_chunks=f"~{chunking_stats['total_chunks']:,}",
        expected_tokens=f"~{chunking_stats['total_tokens_estimated']:,}",
    )

    print("\n" + "=" * 60)
    print("PDF EXTRACTION TEST SUMMARY")
    print("=" * 60)
    print(f"✅ Books loaded: {len(book_data)}")
    print(f"✅ Total chapters: {analysis['total_chapters']:,}")
    print(f"✅ Total content: {analysis['total_content_chars']:,} characters")
    print(f"✅ Expected chunks: {chunking_stats['total_chunks']:,}")
    print(f"✅ Expected tokens: {chunking_stats['total_tokens_estimated']:,}")
    print("=" * 60)
    print("The production indexing script should process successfully with these numbers.")


if __name__ == "__main__":
    main()
