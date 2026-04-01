#!/usr/bin/env python3
"""
Test PDF extraction without OpenAI API dependency.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from app.ai.rag.chunker import detect_language, extract_text_from_pdf, TextChunker


def test_pdf_extraction():
    """Test PDF text extraction for all 3 reference books."""
    resources_dir = Path(__file__).parent.parent / "resources"
    
    if not resources_dir.exists():
        print(f"❌ Resources directory not found: {resources_dir}")
        return False
    
    pdf_files = list(resources_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"❌ No PDF files found in {resources_dir}")
        return False
        
    print(f"📚 Found {len(pdf_files)} PDF files")
    
    chunker = TextChunker(chunk_size=512, overlap_size=50)
    total_chunks = 0
    
    for pdf_file in pdf_files:
        try:
            print(f"\n🔍 Processing: {pdf_file.name}")
            
            # Extract text
            text = extract_text_from_pdf(str(pdf_file))
            
            if not text.strip():
                print(f"  ⚠️ No text extracted from {pdf_file.name}")
                continue
                
            # Detect language
            language = detect_language(text)
            
            # Determine source name
            filename_lower = pdf_file.name.lower()
            if "donaldson" in filename_lower:
                source = "donaldson"
            elif "triola" in filename_lower:
                source = "triola"
            elif "scutchfield" in filename_lower:
                source = "scutchfield"
            else:
                source = pdf_file.stem.lower().replace(" ", "_")
            
            print(f"  📖 Source: {source}")
            print(f"  🌍 Language: {language}")
            print(f"  📝 Text length: {len(text):,} characters")
            
            # Create chunks (without embeddings)
            chunks = list(chunker.chunk_document(
                text=text, 
                source=source, 
                level=2,  # Default level
                language=language
            ))
            
            chunk_count = len(chunks)
            total_chunks += chunk_count
            
            print(f"  🧩 Chunks created: {chunk_count}")
            
            # Show sample chunk
            if chunks:
                sample_chunk = chunks[0]
                preview = sample_chunk.content[:200] + "..." if len(sample_chunk.content) > 200 else sample_chunk.content
                print(f"  📄 Sample chunk: {preview}")
                
        except Exception as e:
            print(f"  ❌ Error processing {pdf_file.name}: {str(e)}")
            
    print(f"\n📊 Summary:")
    print(f"  Total chunks: {total_chunks}")
    print(f"  Files processed: {len(pdf_files)}")
    
    if total_chunks > 0:
        print(f"✅ PDF extraction test successful!")
        return True
    else:
        print(f"❌ PDF extraction test failed!")
        return False


if __name__ == "__main__":
    success = test_pdf_extraction()
    sys.exit(0 if success else 1)