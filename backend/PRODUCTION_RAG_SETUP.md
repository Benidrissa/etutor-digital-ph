# Production RAG Setup Guide

This guide covers the setup and indexing of the RAG (Retrieval-Augmented Generation) pipeline for SantePublique AOF in production.

## Prerequisites

### Environment Variables
```bash
# Required for OpenAI embeddings
export OPENAI_API_KEY="sk-proj-..."

# Database connection (PostgreSQL with pgvector)
export DATABASE_URL="postgresql+asyncpg://user:password@host:port/database"

# Optional: Logging level
export LOG_LEVEL="INFO"
```

### System Requirements
- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- ~500MB free disk space for PDF processing
- Internet connection for OpenAI API calls

### Dependencies
All dependencies are managed through `uv`. The production environment should have:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Setup Process

### 1. Database Preparation
```bash
# Run migrations to create required tables
cd backend
export PATH="$HOME/.local/bin:$PATH"
uv run alembic upgrade head
```

This creates:
- `document_chunks` table for RAG embeddings
- `module_units` table for lesson organization  
- All other required schema updates

### 2. PDF Resources Verification
Ensure the following 3 reference textbooks are in `resources/`:

- `Donaldsons' Essential Public Health Fourth Edition-min.pdf`
- `Marc M. Triola, Mario F. Triola, Jason Roy - Biostatistics for the Biological and Health Sciences (2nd Edition) (2017, Pearson) - libgen.li_compressed (1).pdf`
- `Principles of Public Health Practice (Delmar Series in  -  F_ Douglas Scutchfield, William Keck, C_ William Keck  -  Delmar series in health services  -  An.pdf`

### 3. Run Production Indexing
```bash
cd backend
uv run python production_indexing.py
```

## Expected Results

### Processing Statistics
- **Total chunks**: ~2,667 across all textbooks
- **Token count**: ~1.28M tokens processed
- **Sources breakdown**:
  - Donaldson: ~715 chunks (Essential Public Health)
  - Triola: ~1,054 chunks (Biostatistics) 
  - Scutchfield: ~898 chunks (Public Health Practice)

### Performance Metrics
- **Processing time**: 10-15 minutes (depends on OpenAI API latency)
- **Storage requirements**: ~50MB for embeddings and metadata
- **API calls**: ~2,700 OpenAI embedding requests

## Verification

### 1. Database Check
```sql
-- Check total chunks indexed
SELECT COUNT(*) FROM document_chunks;
-- Expected: ~2,667

-- Check chunks by source
SELECT 
    metadata->>'source' as source,
    COUNT(*) as chunks,
    AVG(LENGTH(content)) as avg_length
FROM document_chunks 
GROUP BY metadata->>'source';
```

### 2. API Endpoint Test
```bash
# Test lesson generation (should return 200, not 500)
curl -X POST "https://your-api.com/api/v1/content/generate-lesson" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -d '{"unit_id": "some-unit-id", "language": "fr"}'

# Test quiz generation (should return 200, not 500)  
curl -X POST "https://your-api.com/api/v1/quiz/generate" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_JWT" \
  -d '{"module_id": "some-module-id", "difficulty": "intermediate"}'
```

## Troubleshooting

### Common Issues

#### 1. "Missing required environment variables"
```bash
# Verify environment variables are set
echo $OPENAI_API_KEY
echo $DATABASE_URL
```

#### 2. "PDF file not found"
```bash
# Check PDF files exist in resources directory
ls -la ../resources/*.pdf
```

#### 3. "Migration failed"
```bash
# Check database connection and permissions
uv run alembic current
uv run alembic history
```

#### 4. "OpenAI API error"
```bash
# Verify API key is valid and has credits
curl -H "Authorization: Bearer $OPENAI_API_KEY" \
  https://api.openai.com/v1/models
```

#### 5. "Database connection failed"
```bash
# Test PostgreSQL connection
psql $DATABASE_URL -c "SELECT version();"

# Verify pgvector extension
psql $DATABASE_URL -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

### Log Analysis
The script uses structured logging. Key log events:
- `"Environment validation passed"` - Prerequisites OK
- `"Migrations completed successfully"` - Database ready
- `"PDF processed successfully"` - Each PDF indexed
- `"Indexing verification complete"` - Final results

### Performance Issues
If processing is slow:
- Check OpenAI API rate limits and quotas
- Verify network connectivity to OpenAI endpoints
- Monitor database connection pool usage
- Consider processing PDFs individually for debugging

## Security Considerations

### API Keys
- Never log OpenAI API keys
- Use environment variables, not config files
- Rotate keys regularly
- Monitor API usage for anomalies

### Database Access
- Use connection pooling in production
- Enable SSL for database connections
- Restrict database user permissions to required operations only

### PDF Processing
- Validate PDF file integrity before processing
- Sandbox PDF processing if handling user uploads
- Monitor disk space during extraction

## Maintenance

### Re-indexing
To update the RAG index with new content:
```bash
# Clear existing chunks (optional)
psql $DATABASE_URL -c "TRUNCATE document_chunks;"

# Run indexing again
uv run python production_indexing.py
```

### Monitoring
Monitor these metrics in production:
- Document chunk count stability
- RAG retrieval latency (should be <100ms)
- Content generation success rate
- OpenAI API usage and costs

### Updates
When updating textbooks or adding new sources:
1. Add new PDFs to `resources/` directory
2. Update `production_indexing.py` to include new files
3. Re-run indexing process
4. Verify all content types generate correctly

## Support

For issues during setup:
1. Check logs for specific error messages
2. Verify all prerequisites are met
3. Test each component individually
4. Consult the main project documentation in `CLAUDE.md`