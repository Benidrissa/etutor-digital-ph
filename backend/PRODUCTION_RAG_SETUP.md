# Production RAG Setup Guide

This guide explains how to set up the RAG (Retrieval-Augmented Generation) pipeline on production for the SantePublique AOF platform.

## Prerequisites

1. **PostgreSQL database** with pgvector extension enabled
2. **Environment variables** properly set:
   - `DATABASE_URL`: PostgreSQL connection string (with asyncpg driver)
   - `OPENAI_API_KEY`: OpenAI API key for embedding generation
3. **3 Reference PDFs** placed in `/resources/` directory:
   - Donaldson's Essential Public Health 
   - Triola's Biostatistics for Health Sciences
   - Scutchfield's Principles of Public Health Practice

## Quick Setup

### Option 1: Automated Production Script (Recommended)

```bash
cd backend
export OPENAI_API_KEY="sk-..."
export DATABASE_URL="postgresql+asyncpg://user:pass@host:port/db"
uv run python production_indexing.py
```

This script will:
1. Run all database migrations
2. Process 3 PDF textbooks into chunks
3. Generate embeddings using OpenAI
4. Store ~2,667 chunks in `document_chunks` table
5. Verify search functionality
6. Display final statistics

**Expected Results:**
- ~2,667 document chunks
- ~1.28M total tokens
- 3 sources: donaldson, triola, scutchfield
- Language: English (en)

### Option 2: Manual Step-by-Step

```bash
cd backend

# 1. Run migrations
uv run alembic upgrade head

# 2. Process PDFs individually
uv run python scripts/rag_pipeline.py process-resources

# 3. Verify search works
uv run python scripts/rag_pipeline.py verify-search

# 4. Check statistics
uv run python scripts/rag_pipeline.py stats
```

## Verification

After setup, verify the pipeline works:

```bash
# Check chunk counts
uv run python scripts/rag_pipeline.py stats

# Test semantic search
uv run python scripts/rag_pipeline.py search "epidemiology surveillance" --top-k=3

# Test lesson generation endpoint
curl -X POST "https://your-api.com/api/v1/content/generate-lesson" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -d '{
    "module_id": "MODULE_UUID",
    "unit_id": "1.1",
    "language": "fr",
    "country": "senegal"
  }'
```

## Database Schema

The setup creates/populates these tables:

### `document_chunks` (RAG vector store)
- ~2,667 rows with embeddings
- Sources: donaldson, triola, scutchfield
- 1536-dim vectors (OpenAI text-embedding-3-small)

### `module_units` (Unit definitions)
- M01: 3 units (1.1, 1.2, 1.3)
- M02: 3 units (2.1, 2.2, 2.3) 
- M03: 3 units (3.1, 3.2, 3.3)

## Troubleshooting

### "OPENAI_API_KEY not set"
```bash
export OPENAI_API_KEY="sk-proj-..."
```

### "No PDF files found"
Ensure PDFs are in `/resources/` directory with correct names.

### "pgvector extension not found"
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### "Low chunk count"
- Check if PDFs are readable (not corrupted/encrypted)
- Verify PDF text extraction: `uv run python test_pdf_extraction.py`

### "Search returns no results"
- Check if embeddings were generated: Look for non-null `embedding` column
- Verify HNSW index exists: `CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops);`

## Performance Notes

- **Indexing time**: ~5-10 minutes for 3 PDFs (depends on API latency)
- **Storage**: ~50MB for chunks + embeddings
- **Memory**: Embedding generation uses ~200MB RAM peak
- **API calls**: ~2,667 embedding API calls (cost: ~$0.40 USD)

## Security

- OpenAI API key is only used server-side
- Embeddings are stored locally in PostgreSQL
- No sensitive data sent to external APIs
- GDPR compliant (no PII in embeddings)

## Next Steps

After successful setup:

1. Test lesson generation: `POST /api/v1/content/generate-lesson`
2. Test quiz generation: `POST /api/v1/quiz/generate`
3. Verify UI components can fetch generated content
4. Set up monitoring for API latency and error rates

The RAG pipeline will now support content generation for modules M01-M03 with proper source citations from the 3 reference textbooks.