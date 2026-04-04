---
name: fastapi-service
description: Build and modify FastAPI backend for the SantePublique AOF learning platform. Use when creating endpoints, domain models, services, RAG pipelines, or Celery tasks. Enforces the 4-layer architecture (Backend → AI/RAG → External Data), async SQLAlchemy, Pydantic V2, Local Auth (TOTP MFA), mobile-first API design, and the exact data model from the SRS.
user-invocable: true
---

# SantePublique AOF FastAPI Backend Builder

Build the production-grade FastAPI backend for SantePublique AOF — an adaptive, bilingual (FR/EN), mobile-first learning platform for public health professionals in West Africa. This backend sits in the second layer of a 4-layer architecture:

```
Frontend (Next.js 15 PWA) → [THIS] Backend (FastAPI + PostgreSQL) → AI/RAG (Claude + pgvector) → External Data (DHIS2, DHS, WHO, PubMed)
```

## Before writing any backend code

1. Read the SRS requirement in `docs/SRS_SantePublique_AOF.md` — match functional requirement IDs (FR-01 through FR-06)
2. Read the syllabus in `docs/syllabus_sante_publique_AOF.md` — understand the 4 levels, 15 modules, ~320 hours curriculum
3. Check the data model (SRS Section 9) — use the exact table schemas defined there
4. Check if similar functionality already exists in the codebase

## Technology stack (non-negotiable)

- Python 3.12 with type hints (mypy strict)
- FastAPI + uvicorn
- SQLAlchemy 2.0 async mode (asyncpg) with PostgreSQL 16
- Alembic for ALL schema changes (NEVER `metadata.create_all()`)
- Redis 7 for caching (generated content, sessions, rate limiting)
- Celery for async tasks (content generation, data pipeline ETL)
- Pydantic V2 for all schemas
- Local Auth (TOTP MFA) (JWT validation) — email, Google OAuth, LinkedIn OAuth
- Anthropic Claude 3.5 Sonnet API (server-side only) for content generation
- pgvector (PostgreSQL extension) for RAG vector store — NO ChromaDB
- Claude Agent SDK (Anthropic) for RAG orchestration and agentic workflows
- OpenAI text-embedding-3-small (1536 dimensions) for embeddings
- PyMuPDF for PDF text extraction
- httpx async for external API calls
- structlog for JSON logging (no `print()`)
- pydantic-settings for config
- ruff for linting/formatting

## Backend directory structure (mirrors 4-layer architecture)

```
backend/
├── app/
│   ├── api/                        # LAYER 2: REST API surface
│   │   ├── v1/
│   │   │   ├── auth.py             # FR-01: register, login, OAuth, placement test trigger
│   │   │   ├── users.py            # FR-01: profile, language/country prefs, level
│   │   │   ├── courses.py          # FR-02: public catalog, enroll/unenroll
│   │   │   ├── admin_courses.py    # FR-02: admin CRUD, publish, AI generate structure
│   │   │   ├── modules.py          # FR-02: list modules, progress, unlock logic
│   │   │   ├── lessons.py          # FR-03: AI-generated lesson viewer (SSE streaming)
│   │   │   ├── quizzes.py          # FR-04: adaptive quiz, submit answers, scores
│   │   │   ├── flashcards.py       # FR-05: FSRS deck, due cards, rate card
│   │   │   ├── tutor.py            # FR-03: AI tutor chat (SSE streaming)
│   │   │   ├── datasets.py         # FR-06: AOF datasets library, sandbox validation
│   │   │   ├── certificates.py     # Certificate generation + download
│   │   │   └── dashboard.py        # FR-02: aggregated stats for dashboard
│   │   ├── schemas/                # Pydantic V2 request/response models per endpoint
│   │   │   ├── auth.py
│   │   │   ├── modules.py
│   │   │   ├── lessons.py
│   │   │   ├── quizzes.py
│   │   │   ├── flashcards.py
│   │   │   ├── tutor.py
│   │   │   └── common.py           # PaginatedResponse, ErrorResponse
│   │   ├── middleware/
│   │   │   ├── cors.py
│   │   │   ├── rate_limit.py       # 100 req/min/IP + 50 tutor msg/day/user
│   │   │   ├── language.py         # Accept-Language → user locale (fr/en)
│   │   │   └── compression.py      # gzip/brotli (critical for 2G/3G)
│   │   └── deps.py                 # Dependency injection: db, auth, services
│   │
│   ├── domain/                     # Business logic (framework-agnostic)
│   │   ├── models/                 # SQLAlchemy 2.0 models (match SRS Section 9)
│   │   │   ├── user.py             # users table
│   │   │   ├── module.py           # modules table (15 modules, 4 levels)
│   │   │   ├── progress.py         # user_module_progress table
│   │   │   ├── content.py          # generated_content table (lesson/quiz/flashcard/case)
│   │   │   ├── quiz.py             # quiz_attempts table
│   │   │   ├── flashcard.py        # flashcard_reviews table (FSRS state)
│   │   │   └── conversation.py     # tutor_conversations table
│   │   ├── services/
│   │   │   ├── auth_service.py           # Local Auth (TOTP MFA) validation, placement test
│   │   │   ├── module_service.py         # Prerequisite checks, unlock logic (80% threshold)
│   │   │   ├── lesson_service.py         # Content generation orchestration
│   │   │   ├── quiz_service.py           # CAT algorithm, scoring, question selection
│   │   │   ├── flashcard_service.py      # FSRS scheduling, due card selection
│   │   │   ├── tutor_service.py          # RAG chat, source citations, rate limiting
│   │   │   └── dashboard_service.py      # Pre-aggregated stats
│   │   └── repositories/           # Protocol-based data access
│   │       ├── protocols.py        # Repository interfaces (Protocol classes)
│   │       └── implementations/    # SQLAlchemy implementations
│   │
│   ├── ai/                         # LAYER 3: AI/RAG engine
│   │   ├── rag/
│   │   │   ├── indexer.py          # PDF → 512-token chunks → embeddings → pgvector
│   │   │   ├── retriever.py        # Top-K (k=8) similarity search with metadata filters
│   │   │   └── generator.py        # Claude API calls with system prompts
│   │   ├── prompts/                # System prompts per content type
│   │   │   ├── lesson.py           # "Tu es un expert en santé publique..."
│   │   │   ├── quiz.py             # QCM generation with 4 options + explanation
│   │   │   ├── flashcard.py        # Bilingual term + definition + AOF example
│   │   │   ├── case_study.py       # AOF context + real data + guided questions
│   │   │   └── tutor.py            # Pedagogical chatbot system prompt
│   │   ├── algorithms/
│   │   │   ├── cat.py              # Computer Adaptive Testing (IRT model)
│   │   │   └── fsrs.py             # FSRS spaced repetition scheduler
│   │   └── embeddings.py           # OpenAI text-embedding-3-small (1536 dims)
│   │
│   ├── integrations/               # LAYER 4: External data sources
│   │   ├── dhis2_client.py         # DHIS2 API — epidemiological data (weekly refresh)
│   │   ├── dhs_client.py           # DHS Program — demographic surveys (monthly)
│   │   ├── who_client.py           # WHO AFRO Open Data — bulletins (weekly)
│   │   ├── worldbank_client.py     # World Bank — health indicators (monthly)
│   │   ├── pubmed_client.py        # PubMed E-utils — recent AOF articles (monthly)
│   │   └── auth_local.py        # Local Auth (TOTP MFA) SDK wrapper
│   │
│   ├── infrastructure/
│   │   ├── persistence/            # SQLAlchemy repository implementations
│   │   ├── cache/
│   │   │   └── redis.py            # Redis cache layer (content, sessions, rate limits)
│   │   └── config/
│   │       └── settings.py         # pydantic-settings: all env vars
│   │
│   ├── tasks/                      # Celery async tasks
│   │   ├── celery_app.py
│   │   ├── content_generation.py   # Bulk pre-generation of lessons per module
│   │   └── data_etl.py             # Scheduled ETL: DHIS2, DHS, WHO, PubMed → Redis
│   │
│   └── main.py                     # FastAPI app factory, middleware, routers
│
├── resources/                      # 3 reference PDFs (indexed by RAG)
│   ├── Donaldson_Essential_PH.pdf
│   ├── Scutchfield_Principles_PH.pdf
│   └── Triola_Biostatistics.pdf
│
├── tests/
│   ├── conftest.py
│   ├── unit/                       # Mock repos, test services + algorithms
│   ├── integration/                # Real PostgreSQL, test endpoints
│   └── fixtures/
│
├── migrations/
│   ├── env.py
│   └── versions/
│
├── alembic.ini
├── Dockerfile
├── pyproject.toml
└── docker-compose.yml              # PostgreSQL (pgvector) + Redis for dev
```

## Data model (match SRS Section 9 exactly)

These are the core tables. All Alembic migrations must produce these schemas:

```python
# domain/models/user.py
class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    preferred_language: Mapped[str]  # "fr" | "en"
    country: Mapped[str]            # ECOWAS country code
    professional_role: Mapped[str]
    current_level: Mapped[int]      # 1-4
    streak_days: Mapped[int] = mapped_column(default=0)
    last_active: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=func.now())

# domain/models/course.py
class Course(Base):
    __tablename__ = "courses"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(unique=True)
    title_fr: Mapped[str]
    title_en: Mapped[str]
    description_fr: Mapped[str | None]
    description_en: Mapped[str | None]
    domain: Mapped[str | None]
    target_audience: Mapped[str | None]
    languages: Mapped[str] = mapped_column(default="fr,en")
    estimated_hours: Mapped[int] = mapped_column(default=20)
    module_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str]  # "draft" | "published" | "archived"
    cover_image_url: Mapped[str | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    rag_collection_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    published_at: Mapped[datetime | None]
    # relationships: modules (one-to-many), enrollments (one-to-many)

class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollment"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    enrolled_at: Mapped[datetime] = mapped_column(default=func.now())
    status: Mapped[str]  # "active" | "completed" | "dropped"
    completion_pct: Mapped[float] = mapped_column(default=0.0)

# domain/models/module.py
class Module(Base):
    __tablename__ = "modules"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    module_number: Mapped[int]
    level: Mapped[int]              # 1-4
    title_fr: Mapped[str]
    title_en: Mapped[str]
    description_fr: Mapped[str]
    description_en: Mapped[str]
    estimated_hours: Mapped[int]
    bloom_level: Mapped[str]
    course_id: Mapped[UUID | None] = mapped_column(ForeignKey("courses.id"))
    prereq_modules: Mapped[list] = mapped_column(ARRAY(UUID))
    books_sources: Mapped[dict] = mapped_column(JSONB)  # {donaldson: [ch2,ch3], triola: [ch4]}

# domain/models/progress.py — PK (user_id, module_id)
class UserModuleProgress(Base):
    __tablename__ = "user_module_progress"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    module_id: Mapped[UUID] = mapped_column(ForeignKey("modules.id"), primary_key=True)
    status: Mapped[str]             # "locked" | "in_progress" | "completed"
    completion_pct: Mapped[float]
    quiz_score_avg: Mapped[float]
    time_spent_minutes: Mapped[int]
    last_accessed: Mapped[datetime]

# domain/models/content.py
class GeneratedContent(Base):
    __tablename__ = "generated_content"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    module_id: Mapped[UUID] = mapped_column(ForeignKey("modules.id"))
    content_type: Mapped[str]       # "lesson" | "quiz" | "flashcard" | "case"
    language: Mapped[str]           # "fr" | "en"
    level: Mapped[int]
    content: Mapped[dict] = mapped_column(JSONB)        # Structured by type
    sources_cited: Mapped[list] = mapped_column(JSONB)  # [{book, chapter, page}]
    country_context: Mapped[str]
    generated_at: Mapped[datetime] = mapped_column(default=func.now())
    validated: Mapped[bool] = mapped_column(default=False)

# domain/models/quiz.py
class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    quiz_id: Mapped[UUID] = mapped_column(ForeignKey("generated_content.id"))
    answers: Mapped[dict] = mapped_column(JSONB)
    score: Mapped[float]
    time_taken_sec: Mapped[int]
    attempted_at: Mapped[datetime] = mapped_column(default=func.now())

# domain/models/flashcard.py — FSRS state
class FlashcardReview(Base):
    __tablename__ = "flashcard_reviews"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    card_id: Mapped[UUID] = mapped_column(ForeignKey("generated_content.id"))
    rating: Mapped[str]             # "again" | "hard" | "good" | "easy"
    next_review: Mapped[datetime]   # Computed by FSRS algorithm
    stability: Mapped[float]        # FSRS parameter
    difficulty: Mapped[float]       # FSRS parameter
    reviewed_at: Mapped[datetime] = mapped_column(default=func.now())

# domain/models/conversation.py
class TutorConversation(Base):
    __tablename__ = "tutor_conversations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    module_id: Mapped[UUID] = mapped_column(ForeignKey("modules.id"))
    messages: Mapped[list] = mapped_column(JSONB)  # [{role, content, sources, timestamp}]
    created_at: Mapped[datetime] = mapped_column(default=func.now())
```

## API endpoints (map to SRS functional requirements)

### FR-01: Authentication & Account (Local Auth (TOTP MFA))
```
POST   /api/v1/auth/register          # Email + profile (language, country, role)
POST   /api/v1/auth/login             # Email/password → JWT
POST   /api/v1/auth/oauth/{provider}  # Google, LinkedIn
GET    /api/v1/users/me               # Current user profile
PATCH  /api/v1/users/me               # Update language, country, preferences
POST   /api/v1/users/me/placement     # Submit placement test → assigns level 1-4
```

### FR-02: Courses, Catalog & Enrollment
```
GET    /api/v1/courses                       # Public catalog (published courses, optional ?domain= ?search=)
GET    /api/v1/courses/my-enrollments        # User's enrolled courses (auth required)
POST   /api/v1/courses/{id}/enroll           # Enroll in published course → creates UserModuleProgress
POST   /api/v1/courses/{id}/unenroll         # Soft-delete enrollment (status="dropped")
GET    /api/v1/admin/courses                 # Admin: list all courses (all statuses)
POST   /api/v1/admin/courses                 # Admin: create course (draft)
GET    /api/v1/admin/courses/{id}            # Admin: course detail
PATCH  /api/v1/admin/courses/{id}            # Admin: update course
DELETE /api/v1/admin/courses/{id}            # Admin: delete (draft only, no enrollments)
POST   /api/v1/admin/courses/{id}/publish    # Admin: publish course
POST   /api/v1/admin/courses/{id}/archive    # Admin: archive course
POST   /api/v1/admin/courses/{id}/generate-structure  # Admin: AI-generate modules via Claude
```

### FR-02bis: Modules & Progression
```
GET    /api/v1/modules                # List modules with user progress + lock status
GET    /api/v1/modules/{id}           # Module detail: units, objectives, progress
GET    /api/v1/dashboard              # Pre-aggregated: streak, progress map, due reviews, recommendations
```

Module unlock rule: module N+1 unlocks when module N reaches `completion_pct >= 80` AND `quiz_score_avg >= 80`.

### FR-03: AI Content Generation (RAG + Claude)
```
GET    /api/v1/modules/{id}/lessons/{unit_id}          # Get/generate lesson (SSE streaming)
GET    /api/v1/modules/{id}/lessons/{unit_id}/stream    # SSE stream endpoint
POST   /api/v1/tutor/messages                          # Send tutor question (SSE streaming response)
GET    /api/v1/tutor/conversations/{id}                # Conversation history
GET    /api/v1/tutor/remaining                         # Daily message count (50/day free)
```

### FR-04: Adaptive Quiz (CAT algorithm)
```
GET    /api/v1/modules/{id}/quiz              # Start/get quiz (10 adaptive questions)
POST   /api/v1/modules/{id}/quiz/answer       # Submit one answer → next question + feedback
POST   /api/v1/modules/{id}/quiz/submit       # Submit full quiz → score + explanations
GET    /api/v1/modules/{id}/quiz/history       # Past attempts
```

### FR-05: Flashcards (FSRS)
```
GET    /api/v1/flashcards/due                  # Today's due cards (across all modules)
GET    /api/v1/modules/{id}/flashcards         # Module flashcard deck
POST   /api/v1/flashcards/{card_id}/review     # Submit FSRS rating (again/hard/good/easy)
GET    /api/v1/flashcards/due?since={ts}       # Delta sync for offline clients
```

### FR-06: Datasets & Sandbox
```
GET    /api/v1/datasets                        # List 20+ AOF datasets
GET    /api/v1/datasets/{id}                   # Dataset detail + download URL
POST   /api/v1/sandbox/validate                # Validate code exercise output
```

## RAG pipeline (3-phase, match SRS Section 6)

### Phase 1 — Indexation (run once + on new data)
```python
# ai/rag/indexer.py
# 1. Extract text from 3 reference PDFs using PyMuPDF
# 2. Chunk into 512-token segments with overlap (64 tokens)
# 3. Attach metadata: {source: "donaldson", chapter: 3, page: 45, level: 2}
# 4. Store chunks + embeddings in pgvector (document_chunks table with ARRAY(Float) column)
```

### Phase 2 — Embeddings
- Model: `text-embedding-3-small` (OpenAI), 1536 dimensions
- Store in pgvector with SQL WHERE filters (source, chapter, level, country)
- Also index: WHO AFRO bulletins, PubMed abstracts, DHIS2 data summaries

### Phase 3 — Dynamic generation (on user request)
```python
# ai/rag/retriever.py — Top-K retrieval using pgvector cosine distance
# Uses raw SQL to avoid asyncpg vector binding issues
async def search(query: str, top_k: int = 8, filters: dict = None) -> list[SearchResult]:
    query_embedding = await embedding_service.generate_embedding(query)
    embedding_literal = "[" + ",".join(str(x) for x in query_embedding) + "]"
    # pgvector cosine distance: 1 - (embedding::vector <=> query::vector)
    query_str = f"""
    SELECT *, 1 - (embedding::vector <=> '{embedding_literal}'::vector) as similarity
    FROM document_chunks
    WHERE embedding IS NOT NULL AND {where_clauses}
    ORDER BY similarity DESC LIMIT :limit
    """
    result = await session.execute(text(query_str).bindparams(**params))
    return [SearchResult(chunk=row, similarity_score=row.similarity) for row in result]

# ai/rag/generator.py — Claude API content generation
async def generate_lesson(chunks, language, country, level, bloom_level) -> GeneratedContent:
    system_prompt = LESSON_PROMPT.format(
        language=language, country=country, level=level, bloom_level=bloom_level
    )
    response = await anthropic.messages.create(
        model="claude-sonnet-4-6",
        system=system_prompt,
        messages=[{"role": "user", "content": format_chunks(chunks)}],
        stream=True,
    )
    # Parse structured output → GeneratedContent with sources_cited
```

### Content types generated (match SRS exactly)

| Type | Structure | Generation params |
|---|---|---|
| **Lesson** | Intro → Concepts → AOF Example → Synthesis → 5 Key Points | module_id, level, langue, pays, bloom_level |
| **Quiz** | 10-20 QCM, 4 options, 1 correct, explanation + source | module_id, difficulty, type (recall/application/analysis) |
| **Flashcard** | Term FR → Definition FR/EN + AOF example + formula | concept_id, main_language, include_formula |
| **Case study** | AOF context → Data → Guided questions → Annotated correction | module_id, pays, disease_type, data_source |
| **Exercise** | Real data (CSV/JSON) → Instructions → Expected results → Solution | stats_method, tool (R/Python), dataset |

## Algorithms

### CAT — Computer Adaptive Testing (FR-04)
```python
# ai/algorithms/cat.py
# Questions classified by difficulty 1-5
# User level estimated by simplified IRT (Item Response Theory)
# Next question selected at ±0.5 from estimated level
# Pool: minimum 50 questions per module
# Stop after 10 questions (formative) or 20 (summative)
```

### FSRS — Free Spaced Repetition Scheduler (FR-05)
```python
# ai/algorithms/fsrs.py
# Ratings: again=1, hard=2, good=3, easy=4
# Computes: next_review datetime, stability, difficulty
# "Quick review" mode: top 10-20 most urgent cards, max 15 min/day
# Fallback to SM-2 if FSRS params unstable for new users
```

## Hard rules

### Claude API — server-side only
- NEVER expose Anthropic API keys to the frontend
- All Claude calls go through FastAPI as a secure proxy
- Use streaming (`stream=True`) for lesson/tutor responses
- Rate limit: 50 tutor messages/day per user (free tier)
- Every generated response MUST include `sources_cited` array

### Local Auth (TOTP MFA)
- Validate JWT on every protected endpoint
- Public endpoints: health, OAuth callbacks
- Extract `user_id`, `preferred_language`, `country` from JWT claims
- Row Level Security (RLS) in PostgreSQL for data isolation between users

### Caching strategy
- `generated_content` table = persistent cache (PostgreSQL)
- Redis TTL cache on top for hot content (lessons, quiz pools, dashboard stats)
- Flashcard FSRS state in PostgreSQL, next-due query cached in Redis
- External data (DHIS2, WHO): Redis with 24h TTL, refreshed by Celery beat

### Content generation — Celery tasks
- Bulk pre-generation of lessons runs as Celery background tasks
- ETL pipelines run on Celery beat: DHIS2/WHO weekly, DHS/PubMed/WorldBank monthly
- Never block API requests with long-running generation

### Health check (required)
```python
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "santepublique-aof-api"}
```

## Mobile-first API design (critical)

This platform targets users on mid-range Android phones over 2G/3G in West Africa.

- **Payload size**: minimal JSON, pagination default 20 items
- **Compression**: gzip/brotli on all responses
- **Streaming**: SSE for all AI-generated content (lessons, tutor)
- **Pagination**: all list endpoints support `?page=&limit=`
- **Sparse fields**: support `?fields=id,title,progress` to reduce payload
- **Offline sync**: delta sync endpoints — `?since={timestamp}` on flashcards, progress
- **Idempotent mutations**: quiz submissions + flashcard ratings safe to retry on flaky connections
- **Request queuing**: accept `X-Offline-Queued-At` header for offline-queued submissions
- **Dashboard**: pre-aggregated stats endpoint, not raw data

```python
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    has_next: bool
```

## Security

- Pydantic validation on EVERY request schema
- SQLAlchemy parameterized queries only (no raw SQL string concatenation)
- Strip HTML from free-text inputs (tutor chat messages)
- Never log: JWT tokens, passwords, API keys, user PII
- Log: resource IDs, pseudonymized user IDs, action types, latencies
- Rate limiting: 100 req/min/IP globally, 50 tutor messages/day/user
- CORS: restrict to frontend origin only
- Content Security Policy headers
- GDPR + West African data protection compliance (Senegal Loi 2008-12, Ghana DPA 2012, Nigeria NDPR 2019, Côte d'Ivoire Loi 2013-450)
- User data deletion endpoint (right to erasure)
- PII minimization: collect only what's needed for learning personalization

## i18n

- All user-facing API text uses translation keys
- Respect `Accept-Language` header (FR primary, EN secondary)
- Generated content stored with `language` field — generate both FR and EN
- Module metadata always has `title_fr` + `title_en`, `description_fr` + `description_en`
- API responses include `language` field

## Performance targets

- API response time: P95 <200ms (non-AI endpoints)
- AI lesson generation: P95 <8s (streaming)
- AI quiz generation: P95 <5s
- Database queries: <50ms P95
- Redis cache hit ratio: >80% for generated content
- JSON payload size: <50KB for list endpoints, <10KB for single items
- 99.5% uptime target
