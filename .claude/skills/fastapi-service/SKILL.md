---
name: fastapi-service
description: Build and modify FastAPI backend for the Sira learning platform. Use when creating endpoints, domain models, services, RAG pipelines, or Celery tasks. Enforces the 3-layer architecture (Backend → AI/RAG), async SQLAlchemy, Pydantic V2, Local Auth (TOTP MFA), mobile-first API design, and the domain model.
user-invocable: true
---

# Sira FastAPI Backend Builder

Build the production-grade FastAPI backend for Sira — an adaptive, bilingual (FR/EN), mobile-first, multi-course learning platform. Originally focused on West Africa, the architecture is domain-agnostic and supports courses in any subject. This backend sits in the second layer of a 3-layer architecture:

```
Frontend (Next.js 15 PWA) → [THIS] Backend (FastAPI + PostgreSQL + Redis) → AI/RAG (Claude API + pgvector + embeddings)
```

## Before writing any backend code

1. Read the SRS in `docs/SRS_Sira.md` — understand the multi-course, multi-curriculum architecture
2. Check the data model in `backend/app/domain/models/` — use the existing table schemas
3. Check if similar functionality already exists in the codebase

## Technology stack (non-negotiable)

- Python 3.12 with type hints (mypy strict)
- FastAPI + uvicorn
- SQLAlchemy 2.0 async mode (asyncpg) with PostgreSQL 16
- Alembic for ALL schema changes (NEVER `metadata.create_all()`)
- Redis 7 for caching (generated content, sessions, rate limiting)
- Celery for async tasks (content generation, RAG indexation, subscriptions, cleanup)
- Pydantic V2 for all schemas
- Local Auth (TOTP MFA) (JWT validation) — email, Google OAuth, LinkedIn OAuth
- Anthropic Claude API (server-side only) for content generation
- Claude Agent SDK (Anthropic) for RAG orchestration and agentic workflows
- pgvector (PostgreSQL extension) for RAG vector store — NO ChromaDB
- OpenAI text-embedding-3-small (1536 dimensions) for embeddings
- PyMuPDF for PDF text extraction
- httpx async for external API calls
- structlog for JSON logging (no `print()`)
- pydantic-settings for config
- ruff for linting/formatting

## Backend directory structure

```
backend/
├── app/
│   ├── api/                        # REST API surface
│   │   ├── v1/
│   │   │   ├── local_auth.py       # Register, login, TOTP MFA, magic link recovery
│   │   │   ├── users.py            # Profile, language/country prefs, level
│   │   │   ├── courses.py          # Public catalog, enroll/unenroll, taxonomy
│   │   │   ├── admin_courses.py    # Admin CRUD, publish, AI generate structure
│   │   │   ├── admin_curricula.py  # Curriculum CRUD, course assignment, access control
│   │   │   ├── admin_taxonomy.py   # Domain/level/audience category management
│   │   │   ├── admin_groups.py     # User group management
│   │   │   ├── admin_settings.py   # Platform settings
│   │   │   ├── analytics.py        # Platform analytics
│   │   │   ├── curricula.py        # Public curriculum catalog
│   │   │   ├── content.py          # Lesson viewer (SSE streaming)
│   │   │   ├── quiz.py             # Adaptive quiz, submit answers, scores
│   │   │   ├── flashcards.py       # FSRS deck, due cards, rate card
│   │   │   ├── tutor.py            # AI tutor chat (SSE streaming)
│   │   │   ├── dashboard.py        # Aggregated stats for dashboard
│   │   │   ├── subscriptions.py    # Subscription management, SMS payments
│   │   │   ├── activation_codes.py # Access code provisioning
│   │   │   ├── course_preassessment.py  # Optional pre-assessment tests
│   │   │   ├── lesson_audio.py     # TTS audio for lessons
│   │   │   ├── placement.py        # Initial placement test
│   │   │   ├── progress.py         # Module/unit progress tracking
│   │   │   ├── images.py           # Generated images
│   │   │   ├── source_images.py    # Source document images
│   │   │   ├── module_media.py     # Module media assets
│   │   │   ├── sms_relay.py        # SMS relay for subscription activation
│   │   │   └── health.py           # Health check endpoint
│   │   ├── schemas/                # Pydantic V2 request/response models per endpoint
│   │   ├── middleware/
│   │   │   ├── cors.py
│   │   │   ├── rate_limit.py       # 100 req/min/IP + daily tutor limits
│   │   │   ├── language.py         # Accept-Language → user locale (fr/en)
│   │   │   └── compression.py      # gzip/brotli (critical for 2G/3G)
│   │   └── deps.py                 # Dependency injection: db, auth, services
│   │
│   ├── domain/                     # Business logic (framework-agnostic)
│   │   ├── models/                 # SQLAlchemy 2.0 models (30+ tables)
│   │   │   ├── user.py             # users table
│   │   │   ├── course.py           # courses, user_course_enrollment
│   │   │   ├── module.py           # modules
│   │   │   ├── module_unit.py      # module_units (lessons, quizzes, case studies)
│   │   │   ├── curriculum.py       # curricula, curriculum_courses
│   │   │   ├── taxonomy.py         # taxonomy_categories, course_taxonomy
│   │   │   ├── course_resource.py  # Uploaded PDFs/CSVs per course
│   │   │   ├── progress.py         # user_module_progress
│   │   │   ├── content.py          # generated_content (lesson/quiz/flashcard/case)
│   │   │   ├── quiz.py             # quiz_attempts
│   │   │   ├── flashcard.py        # flashcard_reviews (FSRS state)
│   │   │   ├── conversation.py     # tutor_conversations
│   │   │   ├── learner_memory.py   # AI tutor learner memory
│   │   │   ├── credit.py           # credit_accounts, transactions, credit_packages
│   │   │   ├── subscription.py     # subscriptions, subscription_payments
│   │   │   ├── user_group.py       # user_groups, members, curriculum_access
│   │   │   ├── preassessment.py    # Course pre-assessment configuration
│   │   │   ├── generated_audio.py  # TTS audio for lessons
│   │   │   ├── generated_image.py  # AI-generated images
│   │   │   ├── source_image.py     # Images extracted from source docs
│   │   │   ├── module_media.py     # Module media assets
│   │   │   ├── document_chunk.py   # RAG chunks with embeddings
│   │   │   ├── activation_code.py  # Access codes
│   │   │   ├── audit_log.py        # Admin audit trail
│   │   │   ├── auth.py             # Auth-related models
│   │   │   ├── sms_relay.py        # SMS relay messages
│   │   │   ├── usage_event.py      # Usage tracking events
│   │   │   └── lesson_reading.py   # Lesson reading progress
│   │   ├── services/
│   │   │   ├── local_auth_service.py     # TOTP MFA, registration, login
│   │   │   ├── jwt_auth_service.py       # JWT token management
│   │   │   ├── lesson_service.py         # Content generation orchestration
│   │   │   ├── quiz_service.py           # CAT algorithm, scoring, question selection
│   │   │   ├── flashcard_service.py      # FSRS scheduling, due card selection
│   │   │   ├── tutor_service.py          # RAG chat, source citations, rate limiting
│   │   │   ├── dashboard_service.py      # Pre-aggregated stats
│   │   │   ├── progress_service.py       # Module/unit progression
│   │   │   ├── syllabus_agent_service.py # AI syllabus generation from uploaded docs
│   │   │   ├── course_agent_service.py   # AI course structure generation
│   │   │   ├── subscription_service.py   # Subscription management
│   │   │   ├── placement_service.py      # Placement test logic
│   │   │   ├── learner_memory_service.py # AI tutor memory management
│   │   │   ├── lesson_audio_service.py   # TTS audio generation
│   │   │   ├── preassessment_generation_service.py  # Pre-assessment generation
│   │   │   ├── analytics_service.py      # Platform analytics
│   │   │   ├── platform_settings_service.py  # Platform config
│   │   │   ├── image_service.py          # Image generation/management
│   │   │   ├── sms_relay_service.py      # SMS relay processing
│   │   │   ├── enrollment_helper.py      # Enrollment utilities
│   │   │   ├── file_processor.py         # PDF/CSV/Word text extraction
│   │   │   ├── email_service.py          # Email sending
│   │   │   ├── activation_code_service.py # Access code management
│   │   │   └── media_summary_service.py  # Media summarization
│   │   └── repositories/           # Protocol-based data access
│   │       ├── protocols.py        # Repository interfaces (Protocol classes)
│   │       └── implementations/    # SQLAlchemy implementations
│   │
│   ├── ai/                         # AI/RAG engine
│   │   ├── rag/
│   │   │   ├── indexer.py          # PDF → 512-token chunks → embeddings → pgvector
│   │   │   ├── retriever.py        # Top-K (k=8) similarity search with metadata filters
│   │   │   └── generator.py        # Claude API calls with system prompts
│   │   ├── prompts/                # System prompts per content type (dynamically set per course topic)
│   │   │   ├── lesson.py           # Lesson generation prompt
│   │   │   ├── quiz.py             # QCM generation with 4 options + explanation
│   │   │   ├── flashcard.py        # Bilingual term + definition + contextual example
│   │   │   ├── case_study.py       # Contextual scenario + data + guided questions
│   │   │   └── tutor.py            # Pedagogical chatbot system prompt
│   │   ├── algorithms/
│   │   │   ├── cat.py              # Computer Adaptive Testing (IRT model)
│   │   │   └── fsrs.py             # FSRS spaced repetition scheduler
│   │   └── embeddings.py           # OpenAI text-embedding-3-small (1536 dims)
│   │
│   ├── integrations/               # External service clients
│   │   └── auth_local.py           # Local Auth SDK wrapper
│   │   # NOTE: DHIS2, DHS, WHO, PubMed clients are planned for a future phase
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
│   │   ├── syllabus_generation.py  # AI syllabus generation from uploaded docs
│   │   ├── rag_indexation.py       # RAG indexation of course resources
│   │   ├── image_indexation.py     # Image extraction and indexation
│   │   ├── preassessment_generation.py  # Pre-assessment generation
│   │   ├── subscription.py         # Subscription lifecycle tasks
│   │   ├── sms_relay.py            # SMS processing tasks
│   │   ├── file_cleanup.py         # Cleanup expired uploads/drafts
│   │   └── data_etl.py             # Scheduled ETL (future: DHIS2, WHO data)
│   │
│   └── main.py                     # FastAPI app factory, middleware, routers
│
├── resources/                      # Course-specific PDFs uploaded via API
│                                   # Each course has its own document set in course_resources table
├── tests/
│   ├── conftest.py
│   └── ...                         # Unit + integration tests
│
├── migrations/
│   ├── env.py
│   └── versions/                   # 62+ Alembic migrations
│
├── alembic.ini
├── Dockerfile
├── pyproject.toml
└── docker-compose.yml              # PostgreSQL (pgvector) + Redis for dev
```

## Data model (key entities)

These are the core tables. All Alembic migrations must produce these schemas:

```python
# domain/models/user.py
class User(Base):
    __tablename__ = "users"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    preferred_language: Mapped[str]  # "fr" | "en"
    country: Mapped[str]            # Country code
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
    taxonomy_categories: Mapped[list[TaxonomyCategory]]  # via course_taxonomy junction
    languages: Mapped[str] = mapped_column(default="fr,en")
    estimated_hours: Mapped[int] = mapped_column(default=20)
    module_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str]  # "draft" | "published" | "archived"
    visibility: Mapped[str]  # "public" | "private"
    cover_image_url: Mapped[str | None]
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    rag_collection_id: Mapped[str | None]
    price_credits: Mapped[int]  # 0 = free
    is_marketplace: Mapped[bool] = mapped_column(default=False)
    expert_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    creation_step: Mapped[str]  # "upload" | "generating" | "published"

class UserCourseEnrollment(Base):
    __tablename__ = "user_course_enrollment"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    status: Mapped[str]  # "active" | "completed" | "dropped"
    completion_pct: Mapped[float] = mapped_column(default=0.0)

# domain/models/module.py
class Module(Base):
    __tablename__ = "modules"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    module_number: Mapped[int]
    level: Mapped[int]
    title_fr: Mapped[str]
    title_en: Mapped[str]
    description_fr: Mapped[str]
    description_en: Mapped[str]
    estimated_hours: Mapped[int]
    bloom_level: Mapped[str]
    course_id: Mapped[UUID | None] = mapped_column(ForeignKey("courses.id"))
    prereq_modules: Mapped[list] = mapped_column(ARRAY(UUID))
    books_sources: Mapped[dict] = mapped_column(JSONB)

# domain/models/curriculum.py
class Curriculum(Base):
    __tablename__ = "curricula"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(unique=True)
    title_fr: Mapped[str]
    title_en: Mapped[str]
    description_fr: Mapped[str | None]
    description_en: Mapped[str | None]
    status: Mapped[str]  # "draft" | "published" | "archived"
    visibility: Mapped[str]  # "public" | "private"

class CurriculumCourse(Base):
    __tablename__ = "curriculum_courses"
    curriculum_id: Mapped[UUID] = mapped_column(ForeignKey("curricula.id"), primary_key=True)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"), primary_key=True)
    sort_order: Mapped[int]

# domain/models/taxonomy.py
class TaxonomyCategory(Base):
    __tablename__ = "taxonomy_categories"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    type: Mapped[str]  # "domain" | "level" | "audience"
    slug: Mapped[str] = mapped_column(unique=True)
    label_fr: Mapped[str]
    label_en: Mapped[str]
    sort_order: Mapped[int]
    is_active: Mapped[bool] = mapped_column(default=True)

# domain/models/course_resource.py
class CourseResource(Base):
    __tablename__ = "course_resources"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    course_id: Mapped[UUID] = mapped_column(ForeignKey("courses.id"))
    filename: Mapped[str]
    raw_text: Mapped[str | None]
    toc_json: Mapped[dict | None] = mapped_column(JSONB)
    char_count: Mapped[int]
    content_hash: Mapped[str]
    summary_text: Mapped[str | None]

# domain/models/content.py
class GeneratedContent(Base):
    __tablename__ = "generated_content"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    module_id: Mapped[UUID] = mapped_column(ForeignKey("modules.id"))
    content_type: Mapped[str]       # "lesson" | "quiz" | "flashcard" | "case"
    language: Mapped[str]           # "fr" | "en"
    level: Mapped[int]
    content: Mapped[dict] = mapped_column(JSONB)
    sources_cited: Mapped[list] = mapped_column(JSONB)
    country_context: Mapped[str]
    generated_at: Mapped[datetime] = mapped_column(default=func.now())
    validated: Mapped[bool] = mapped_column(default=False)

# domain/models/credit.py
class CreditAccount(Base):
    __tablename__ = "credit_accounts"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    balance: Mapped[int] = mapped_column(default=0)
    total_purchased: Mapped[int] = mapped_column(default=0)
    total_spent: Mapped[int] = mapped_column(default=0)
    total_earned: Mapped[int] = mapped_column(default=0)

class Transaction(Base):
    __tablename__ = "transactions"
    account_id: Mapped[UUID] = mapped_column(ForeignKey("credit_accounts.id"))
    type: Mapped[str]  # credit_purchase|content_access|tutor_usage|course_purchase|course_earning|commission|payout|...
    amount: Mapped[int]  # signed: positive=credit, negative=debit
    balance_after: Mapped[int]

# domain/models/subscription.py
class Subscription(Base):
    __tablename__ = "subscriptions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    daily_message_limit: Mapped[int]
    status: Mapped[str]  # "active" | "expired" | "cancelled"

# domain/models/user_group.py
class UserGroup(Base):
    __tablename__ = "user_groups"
    name: Mapped[str]
    # members via user_group_members junction

class CurriculumAccess(Base):
    __tablename__ = "curriculum_access"
    curriculum_id: Mapped[UUID] = mapped_column(ForeignKey("curricula.id"))
    user_id: Mapped[UUID | None]
    group_id: Mapped[UUID | None]
```

For full model definitions, see `backend/app/domain/models/`. Additional models include: `quiz.py`, `flashcard.py`, `conversation.py`, `learner_memory.py`, `generated_audio.py`, `preassessment.py`, `audit_log.py`, `activation_code.py`, `usage_event.py`, `lesson_reading.py`, `generated_image.py`, `source_image.py`, `module_media.py`, `sms_relay.py`.

## API endpoints

### Authentication & Account
```
POST   /api/v1/auth/register          # Email + profile (language, country, role)
POST   /api/v1/auth/login             # Email/TOTP → JWT
GET    /api/v1/users/me               # Current user profile
PATCH  /api/v1/users/me               # Update language, country, preferences
POST   /api/v1/users/me/placement     # Submit placement test → assigns level
```

### Courses, Catalog & Enrollment
```
GET    /api/v1/courses/taxonomy               # Public: active taxonomy values with FR/EN labels
GET    /api/v1/courses                       # Public catalog (?course_domain= ?course_level= ?audience_type= ?search=)
GET    /api/v1/courses/my-enrollments        # User's enrolled courses
POST   /api/v1/courses/{id}/enroll           # Enroll in published course
POST   /api/v1/courses/{id}/unenroll         # Soft-delete enrollment
```

### Admin: Courses
```
GET    /api/v1/admin/courses                 # List all courses (all statuses)
POST   /api/v1/admin/courses                 # Create course (draft)
PATCH  /api/v1/admin/courses/{id}            # Update course
DELETE /api/v1/admin/courses/{id}            # Delete (draft only)
POST   /api/v1/admin/courses/{id}/publish    # Publish course
POST   /api/v1/admin/courses/{id}/archive    # Archive course
POST   /api/v1/admin/courses/{id}/generate-structure  # AI-generate modules from uploaded PDFs
```

### Admin: Curricula
```
GET    /api/v1/admin/curricula               # List all curricula
POST   /api/v1/admin/curricula               # Create curriculum
PATCH  /api/v1/admin/curricula/{id}          # Update curriculum
PUT    /api/v1/admin/curricula/{id}/courses  # Assign courses to curriculum
PUT    /api/v1/admin/curricula/{id}/visibility  # Set public/private
POST   /api/v1/admin/curricula/{id}/access   # Grant user/group access
DELETE /api/v1/admin/curricula/{id}/access   # Revoke access
```

### Admin: Taxonomy, Groups, Settings
```
GET    /api/v1/admin/taxonomy                # List taxonomy categories
POST   /api/v1/admin/taxonomy                # Create category
PATCH  /api/v1/admin/taxonomy/{id}           # Update label/sort/active
DELETE /api/v1/admin/taxonomy/{id}           # Delete if unused
GET    /api/v1/admin/groups                  # List user groups
POST   /api/v1/admin/groups                  # Create group
```

### Public Curricula
```
GET    /api/v1/curricula                     # Published curricula catalog
GET    /api/v1/curricula/{slug}              # Curriculum detail with courses
```

### Modules & Progression
```
GET    /api/v1/modules                # List modules with user progress + lock status
GET    /api/v1/modules/{id}           # Module detail: units, objectives, progress
GET    /api/v1/dashboard              # Pre-aggregated: streak, progress, due reviews
```

Module unlock rule: module N+1 unlocks when module N reaches `completion_pct >= 80` AND `quiz_score_avg >= 80`.

### AI Content Generation (RAG + Claude)
```
GET    /api/v1/modules/{id}/lessons/{unit_id}          # Get/generate lesson (SSE streaming)
GET    /api/v1/modules/{id}/lessons/{unit_id}/stream    # SSE stream endpoint
POST   /api/v1/tutor/messages                          # Send tutor question (SSE streaming)
GET    /api/v1/tutor/conversations/{id}                # Conversation history
GET    /api/v1/tutor/remaining                         # Daily message count
```

### Adaptive Quiz (CAT algorithm)
```
GET    /api/v1/modules/{id}/quiz              # Start/get quiz
POST   /api/v1/modules/{id}/quiz/answer       # Submit one answer → next question
POST   /api/v1/modules/{id}/quiz/submit       # Submit full quiz → score
```

### Flashcards (FSRS)
```
GET    /api/v1/flashcards/due                  # Today's due cards
GET    /api/v1/modules/{id}/flashcards         # Module flashcard deck
POST   /api/v1/flashcards/{card_id}/review     # Submit FSRS rating
```

### Subscriptions
```
GET    /api/v1/subscriptions/status            # Current subscription status
POST   /api/v1/subscriptions/activate          # Activate via code/SMS
```

### Lesson Audio
```
GET    /api/v1/lessons/{id}/audio              # Get/generate TTS audio
```

## RAG pipeline (per-course)

### Phase 1 — Indexation (on course resource upload)
```python
# ai/rag/indexer.py
# 1. Extract text from course-specific uploaded PDFs using PyMuPDF
# 2. Chunk into 512-token segments with overlap (64 tokens)
# 3. Attach metadata: {source, chapter, page, course_id}
# 4. Store chunks + embeddings in pgvector (document_chunks table)
```

### Phase 2 — Embeddings
- Model: `text-embedding-3-small` (OpenAI), 1536 dimensions
- Store in pgvector with SQL WHERE filters (source, chapter, level, course_id)

### Phase 3 — Dynamic generation (on user request)
```python
# ai/rag/retriever.py — Top-K retrieval using pgvector cosine distance
# Filters by course_id to retrieve only the relevant course's documents
async def search(query: str, top_k: int = 8, filters: dict = None) -> list[SearchResult]:
    ...

# ai/rag/generator.py — Claude API content generation
# System prompt is dynamically set per course topic, not hardcoded
async def generate_lesson(chunks, language, country, level, bloom_level) -> GeneratedContent:
    ...
```

### Content types generated

| Type | Structure | Generation params |
|---|---|---|
| **Lesson** | Intro → Concepts → Contextual Example → Synthesis → 5 Key Points | module_id, level, langue, pays, bloom_level |
| **Quiz** | 10-20 QCM, 4 options, 1 correct, explanation + source | module_id, difficulty, type (recall/application/analysis) |
| **Flashcard** | Term FR → Definition FR/EN + contextual example + formula | concept_id, main_language, include_formula |
| **Case study** | Contextual scenario → Data → Guided questions → Annotated correction | module_id, pays, topic, data_source |

## Algorithms

### CAT — Computer Adaptive Testing
```python
# ai/algorithms/cat.py
# Questions classified by difficulty 1-5
# User level estimated by simplified IRT (Item Response Theory)
# Next question selected at ±0.5 from estimated level
# Stop after 10 questions (formative) or 20 (summative)
```

### FSRS — Free Spaced Repetition Scheduler
```python
# ai/algorithms/fsrs.py
# Ratings: again=1, hard=2, good=3, easy=4
# Computes: next_review datetime, stability, difficulty
# "Quick review" mode: top 10-20 most urgent cards, max 15 min/day
```

## Hard rules

### Claude API — server-side only
- NEVER expose Anthropic API keys to the frontend
- All Claude calls go through FastAPI as a secure proxy
- Use streaming (`stream=True`) for lesson/tutor responses
- Rate limiting per subscription tier
- Every generated response MUST include `sources_cited` array

### Local Auth (TOTP MFA)
- Validate JWT on every protected endpoint
- Public endpoints: health, OAuth callbacks, public catalog
- Extract `user_id`, `preferred_language`, `country` from JWT claims
- Row Level Security (RLS) in PostgreSQL for data isolation between users

### Caching strategy
- `generated_content` table = persistent cache (PostgreSQL)
- Redis TTL cache on top for hot content (lessons, quiz pools, dashboard stats)
- Flashcard FSRS state in PostgreSQL, next-due query cached in Redis

### Content generation — Celery tasks
- Bulk pre-generation of lessons runs as Celery background tasks
- Syllabus generation from uploaded PDFs runs as Celery task
- RAG indexation of course resources runs as Celery task
- Never block API requests with long-running generation

### Health check (required)
```python
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "sira-api"}
```

## Mobile-first API design (critical)

This platform targets users on mid-range Android phones over 2G/3G, primarily in West Africa.

- **Payload size**: minimal JSON, pagination default 20 items
- **Compression**: gzip/brotli on all responses
- **Streaming**: SSE for all AI-generated content (lessons, tutor)
- **Pagination**: all list endpoints support `?page=&limit=`
- **Sparse fields**: support `?fields=id,title,progress` to reduce payload
- **Offline sync**: delta sync endpoints — `?since={timestamp}` on flashcards, progress
- **Idempotent mutations**: quiz submissions + flashcard ratings safe to retry on flaky connections
- **Request queuing**: accept `X-Offline-Queued-At` header for offline-queued submissions
- **Dashboard**: pre-aggregated stats endpoint, not raw data

## Security

- Pydantic validation on EVERY request schema
- SQLAlchemy parameterized queries only (no raw SQL string concatenation)
- Strip HTML from free-text inputs (tutor chat messages)
- Never log: JWT tokens, passwords, API keys, user PII
- Rate limiting: 100 req/min/IP globally, daily tutor limits per subscription
- CORS: restrict to frontend origin only
- Content Security Policy headers
- GDPR + West African data protection compliance
- User data deletion endpoint (right to erasure)

## i18n

- All user-facing API text uses translation keys
- Respect `Accept-Language` header (FR primary, EN secondary)
- Generated content stored with `language` field — generate both FR and EN
- Module/course metadata always has `title_fr` + `title_en`, `description_fr` + `description_en`

## Performance targets

- API response time: P95 <200ms (non-AI endpoints)
- AI lesson generation: P95 <8s (streaming)
- AI quiz generation: P95 <5s
- Database queries: <50ms P95
- Redis cache hit ratio: >80% for generated content
- JSON payload size: <50KB for list endpoints, <10KB for single items
- 99.5% uptime target
