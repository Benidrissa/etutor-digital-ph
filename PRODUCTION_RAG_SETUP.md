# Production RAG Pipeline Setup

This document provides step-by-step instructions for setting up the RAG (Retrieval-Augmented Generation) pipeline in production to fix the lesson/quiz generation 500 errors.

## Issue Summary

- **Problem**: `POST /api/v1/content/generate-lesson` and `POST /api/v1/quiz/generate` return 500 errors
- **Root Cause**: `document_chunks` table is empty (0 rows) - PDFs were never indexed
- **Solution**: Run the RAG indexing pipeline with proper API keys and database setup

## Prerequisites

1. **Database Access**: PostgreSQL database with all migrations applied
2. **API Keys**: 
   - `OPENAI_API_KEY` for text embeddings (text-embedding-3-small)
   - `ANTHROPIC_API_KEY` for content generation (Claude 3.5 Sonnet)
3. **Reference PDFs**: Located in `/resources/` directory:
   - Donaldson's Essential Public Health (4th Edition)
   - Triola's Biostatistics for Biological and Health Sciences (2nd Edition) 
   - Scutchfield's Principles of Public Health Practice

## Step-by-Step Setup

### 1. Environment Setup

```bash
# Set required environment variables
export OPENAI_API_KEY="sk-..." 
export ANTHROPIC_API_KEY="sk-ant-..."
export DATABASE_URL="postgresql+asyncpg://user:pass@host:port/santepublique_aof"
```

### 2. Run Database Migrations

```bash
cd backend
uv run alembic upgrade head
```

This will create:
- `document_chunks` table for storing text chunks with embeddings
- `module_units` table for unit-level content organization  
- All other required tables and indexes

### 3. Run RAG Pipeline Indexing

```bash
cd backend
uv run python production_indexing.py
```

This script will:
- ✅ Verify environment variables are set
- ✅ Run database migrations to ensure schema is up-to-date
- ✅ Extract text from all 3 reference PDFs
- ✅ Split text into 512-token chunks with 50-token overlap
- ✅ Generate embeddings using OpenAI text-embedding-3-small
- ✅ Store chunks and embeddings in `document_chunks` table
- ✅ Create indexes for efficient vector similarity search
- ✅ Verify indexing was successful

Expected output:
```
🚀 Starting Production RAG Pipeline Indexing
✅ Environment check passed
✅ Database migrations completed successfully
✅ Embedding service ready
📁 Resources directory: ../resources
✅ PDF indexing completed
✅ Verification completed

📊 RAG PIPELINE INDEXING REPORT
============================================================
📚 PDFs Processed: 3
📄 Total Chunks: ~2,500
   - donaldson: ~800 chunks
   - triola: ~900 chunks  
   - scutchfield: ~800 chunks
🔍 Database Verification:
   - Total chunks in DB: 2,500
   - Total tokens: ~1,280,000
   - Avg tokens/chunk: 512.0
   - Sources: donaldson, triola, scutchfield
   - Languages: en

✅ RAG pipeline ready for content generation!
🚀 Lesson and quiz generation endpoints should now work correctly.
```

### 4. Verify Content Generation

Test the endpoints that were previously failing:

```bash
# Test lesson generation
curl -X POST "https://your-api.com/api/v1/content/generate-lesson" \
  -H "Content-Type: application/json" \
  -d '{
    "module_id": "your-module-id",
    "unit_id": "1.1",
    "language": "fr"
  }'

# Test quiz generation  
curl -X POST "https://your-api.com/api/v1/quiz/generate" \
  -H "Content-Type: application/json"
  -d '{
    "module_id": "your-module-id", 
    "unit_id": "1.1",
    "language": "fr"
  }'
```

Both should now return 200 with generated content instead of 500 errors.

## Troubleshooting

### Common Issues

1. **"No relevant content found"**
   - Check that `document_chunks` table has data: `SELECT COUNT(*) FROM document_chunks;`
   - Verify embeddings were generated: `SELECT COUNT(*) FROM document_chunks WHERE embedding IS NOT NULL;`

2. **OpenAI API errors** 
   - Verify API key is valid: `curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models`
   - Check rate limits and billing

3. **Database connection issues**
   - Test connection: `psql "$DATABASE_URL" -c "SELECT 1;"`
   - Verify database exists and user has proper permissions

4. **Missing PDFs**
   - Ensure all 3 PDFs are in `/resources/` directory
   - Check file permissions are readable

### Manual Verification

Check indexing results directly in database:

```sql
-- Count total chunks
SELECT COUNT(*) as total_chunks FROM document_chunks;

-- Chunks per source
SELECT source, COUNT(*) as chunk_count 
FROM document_chunks 
GROUP BY source;

-- Sample chunk content
SELECT source, left(content, 100) as preview, token_count
FROM document_chunks 
LIMIT 5;

-- Check embeddings exist
SELECT COUNT(*) as chunks_with_embeddings 
FROM document_chunks 
WHERE embedding IS NOT NULL;
```

### Re-running Indexing

If you need to re-run the indexing process:

```bash
# Clear existing chunks (optional)
uv run python scripts/rag_pipeline.py clear-source donaldson
uv run python scripts/rag_pipeline.py clear-source triola  
uv run python scripts/rag_pipeline.py clear-source scutchfield

# Re-index everything
uv run python production_indexing.py
```

## Architecture Notes

The RAG pipeline follows this flow:

1. **Extraction**: PyMuPDF extracts text from reference PDFs
2. **Chunking**: Text split into 512-token chunks with 50-token overlap  
3. **Embedding**: OpenAI text-embedding-3-small generates 1536-dim vectors
4. **Storage**: Chunks + embeddings stored in PostgreSQL with pgvector
5. **Retrieval**: Semantic search finds top-K relevant chunks for generation
6. **Generation**: Claude 3.5 Sonnet generates lessons/quizzes from retrieved context

The system is designed to be:
- **Idempotent**: Safe to re-run indexing multiple times
- **Scalable**: Batch processing with async/await
- **Reliable**: Comprehensive error handling and verification
- **Efficient**: Optimized database queries and vector search

## Production Monitoring

Monitor these metrics in production:

- **Database**: `document_chunks` table size and query performance
- **API**: OpenAI embedding API usage and costs
- **Generation**: Claude API usage and response times  
- **Content**: Generated lesson/quiz quality and user feedback

The indexing process typically needs to run only once, unless:
- New reference materials are added
- Database is restored from backup without chunks
- Significant updates to chunking or embedding logic