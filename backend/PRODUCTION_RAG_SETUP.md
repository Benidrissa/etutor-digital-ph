# Production RAG Setup Guide

This guide explains how to set up the complete RAG (Retrieval-Augmented Generation) pipeline for the SantePublique AOF learning platform in production.

## Overview

The RAG pipeline processes 3 reference textbooks into searchable chunks with embeddings:
- **Donaldson**: Essential Public Health textbook
- **Triola**: Biostatistics textbook  
- **Scutchfield**: Principles of Public Health textbook

**Expected Output**: ~2,500-3,000 chunks, ~1.2M-1.5M tokens total

## Prerequisites

### 1. Database Setup
- PostgreSQL 16+ with pgvector extension
- Database with proper credentials and network access

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Environment Variables

Set the following environment variables:

```bash
# Required - PostgreSQL connection with async driver
export DATABASE_URL="postgresql+asyncpg://user:password@host:port/database"

# Required - OpenAI API key for embeddings
export OPENAI_API_KEY="sk-..."
```

### 3. Dependencies

Ensure all Python dependencies are installed:

```bash
cd backend
uv sync
```

## Production Setup Steps

### Step 1: Verify Environment

Test the setup without running the full indexing:

```bash
cd backend
uv run python production_indexing.py --verify-only
```

This will:
- ✅ Check environment variables
- ✅ Test database connection
- ✅ Verify pgvector extension
- ✅ Run database migrations
- ✅ Confirm all tables exist

### Step 2: Run Full Indexing

Once verification passes, run the complete indexing:

```bash
uv run python production_indexing.py
```

**Expected Duration**: 5-15 minutes depending on OpenAI API rate limits

The script will:
1. Process 3 pre-extracted textbooks (JSON files in `data/extracted/`)
2. Create ~2,500 text chunks (512 tokens each with overlap)
3. Generate 1536-dimensional embeddings using OpenAI text-embedding-3-small
4. Store chunks and embeddings in PostgreSQL with pgvector

### Step 3: Clear and Re-index (Optional)

To clear existing data and start fresh:

```bash
uv run python production_indexing.py --clear
```

## Verification

### Check Database Contents

Verify chunks were stored correctly:

```sql
-- Count total chunks
SELECT COUNT(*) FROM document_chunks;

-- Count by source book
SELECT source, COUNT(*) as count 
FROM document_chunks 
GROUP BY source 
ORDER BY source;

-- Check total tokens
SELECT SUM(token_count) as total_tokens 
FROM document_chunks;

-- Sample chunk content
SELECT source, chapter, LEFT(content, 100) || '...' as preview
FROM document_chunks 
LIMIT 5;
```

Expected results:
- **donaldson**: ~900-1000 chunks
- **triola**: ~800-900 chunks  
- **scutchfield**: ~800-900 chunks
- **Total tokens**: ~1.2M-1.5M

### Test API Endpoints

Once indexing is complete, test the content generation endpoints:

```bash
# Test lesson generation
curl -X POST http://localhost:8000/api/v1/content/generate-lesson \\
  -H "Content-Type: application/json" \\
  -d '{
    "module_id": "550e8400-e29b-41d4-a716-446655440000",
    "unit_id": "1.1",
    "language": "fr", 
    "country": "SN",
    "level": 2
  }'

# Test quiz generation  
curl -X POST http://localhost:8000/api/v1/content/generate-quiz \\
  -H "Content-Type: application/json" \\
  -d '{
    "module_id": "550e8400-e29b-41d4-a716-446655440000",
    "unit_id": "1.1",
    "language": "fr",
    "difficulty_level": "medium"
  }'
```

Both should return 200 with generated content instead of 500 errors.

## Troubleshooting

### Common Issues

**1. Database Connection Failed**
```
Error: Database connection failed
```
- Verify DATABASE_URL format: `postgresql+asyncpg://user:pass@host:port/db`
- Check network connectivity to database
- Ensure database exists and user has proper permissions

**2. pgvector Extension Missing**
```
Error: pgvector extension not found
```
- Connect to database as superuser
- Run: `CREATE EXTENSION vector;`

**3. OpenAI API Key Invalid**
```
Error: OPENAI_API_KEY environment variable is required
```
- Verify API key starts with `sk-`
- Check key has sufficient credits/rate limits
- Test key: `curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models`

**4. Migration Failures**
```
Error: Migration failed
```
- Check database permissions (CREATE, DROP, ALTER)
- Ensure no conflicting schema changes
- Review Alembic migration files in `migrations/versions/`

**5. Rate Limiting**
```
Error: OpenAI API rate limit exceeded
```
- Wait and retry (script will auto-retry with backoff)
- Consider upgrading OpenAI plan for higher limits
- Process in smaller batches if needed

### Performance Notes

- **Memory Usage**: ~500MB-1GB during processing
- **API Calls**: ~25-30 embedding requests (100 chunks/batch)
- **Network**: ~10-50MB total OpenAI API traffic
- **Disk**: ~100MB additional database storage

### Security Considerations

1. **API Key Security**
   - Never commit OpenAI API keys to source control
   - Use environment variables or secure secret management
   - Rotate keys periodically

2. **Database Security**  
   - Use strong passwords for database connections
   - Enable SSL/TLS for database connections in production
   - Restrict network access to database

3. **Rate Limiting**
   - OpenAI API has rate limits per organization
   - Monitor usage to avoid unexpected charges
   - Consider implementing request caching

## Next Steps

Once RAG indexing is complete:

1. ✅ **Test Content Generation**: Verify lesson/quiz endpoints return 200
2. ✅ **Monitor Performance**: Check response times (target <8s for lessons)
3. ✅ **Set up Monitoring**: Track embedding usage and API costs
4. 🔄 **Schedule Re-indexing**: Plan for updating with new content
5. 📈 **Scale Resources**: Monitor database size and query performance

The platform should now be ready to generate personalized, contextual content for public health learners across West Africa!