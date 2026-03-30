#!/usr/bin/env python3
"""CLI script for extracting text from reference PDFs."""

import asyncio
import sys
from pathlib import Path

# Add the backend app directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.ai.rag.indexer import RAGIndexer


async def main():
    """Main extraction function."""
    # Default paths
    resources_path = Path(__file__).parent.parent.parent / "resources"
    output_path = Path(__file__).parent.parent / "data" / "extracted"

    # Allow command line overrides
    if len(sys.argv) >= 2:
        resources_path = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])

    print(f"Extracting PDFs from: {resources_path}")
    print(f"Output directory: {output_path}")

    # Check if resources path exists
    if not resources_path.exists():
        print(f"Error: Resources directory not found: {resources_path}")
        sys.exit(1)

    # Check for PDF files
    pdf_files = list(resources_path.glob("*.pdf"))
    if not pdf_files:
        print(f"Error: No PDF files found in {resources_path}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDF files:")
    for pdf_file in pdf_files:
        print(f"  - {pdf_file.name}")

    # Initialize indexer
    indexer = RAGIndexer(str(resources_path), str(output_path))

    try:
        print("\n--- Starting extraction ---")

        # Extract all content
        content = await indexer.extract_all_content()

        print(f"\nExtracted content from {len(content)} books:")
        for book_id, chapters in content.items():
            print(f"  {book_id}: {len(chapters)} chapters")

        # Save to JSON files
        created_files = await indexer.save_extracted_content(content)

        print(f"\nSaved {len(created_files)} files:")
        for file_path in created_files:
            print(f"  - {file_path}")

        # Display statistics
        print("\n--- Content Statistics ---")
        stats = indexer.get_content_statistics()

        if "_totals" in stats:
            totals = stats["_totals"]
            print(f"Total books: {totals['books']}")
            print(f"Total chapters: {totals['chapters']}")
            print(f"Total pages: {totals['pages']}")
            print(f"Total equations: {totals['equations']}")
            print(f"Total content length: {totals['content_length']:,} characters")

        print("\nPer-book statistics:")
        for book_id, book_stats in stats.items():
            if book_id == "_totals":
                continue

            print(f"\n{book_id.upper()}:")
            print(f"  Chapters: {book_stats['chapter_count']}")
            print(f"  Pages: {book_stats['total_pages']}")
            print(f"  Equations: {book_stats['total_equations']}")
            print(f"  Content: {book_stats['total_content_length']:,} characters")

        # Test chunking
        print("\n--- Testing Chunking ---")
        chunks = indexer.prepare_chunks_for_embedding(max_chunk_size=512, overlap=64)
        print(f"Generated {len(chunks)} chunks for embedding")

        # Show sample chunk
        if chunks:
            sample_chunk = chunks[0]
            print("\nSample chunk:")
            print(f"  ID: {sample_chunk['chunk_id']}")
            print(f"  Source: {sample_chunk['metadata']['source_book']}")
            print(f"  Chapter: {sample_chunk['metadata']['chapter_title']}")
            print(f"  Length: {len(sample_chunk['content'])} characters")
            print(f"  Preview: {sample_chunk['content'][:100]}...")

        print("\n✅ Extraction completed successfully!")

    except Exception as e:
        print(f"\n❌ Error during extraction: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
