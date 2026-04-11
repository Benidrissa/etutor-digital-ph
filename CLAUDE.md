# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Sira** (from Bambara *Donniya Sira* — "the path to knowledge") — an adaptive, bilingual (FR/EN), mobile-first, multi-course learning platform. Uses AI (Claude API + RAG) to generate personalized content from any uploaded PDFs. Originally designed for public health professionals in West Africa; the architecture is now fully domain-agnostic and supports courses in any subject.

**Current status:** Production-ready monorepo with 62+ Alembic migrations, dynamic multi-course system, expert marketplace, credit/subscription billing, curricula with access control, admin-managed taxonomy, AI-powered course generation from arbitrary documents, offline-first PWA with background sync, and lesson audio generation.

## Tech Stack

- **Frontend:** Next.js 15 + React 19, Tailwind CSS + shadcn/ui, Zustand, TanStack Query, next-intl (i18n), Serwist/Workbox (Service Worker + offline), IndexedDB via idb/Dexie.js (offline course modules)
- **Backend:** FastAPI (Python 3.12), PostgreSQL 16 + pgvector, Redis 7, Celery
- **Auth:** Local FastAPI auth — passwordless TOTP MFA (Microsoft/Google Authenticator) + email magic link recovery. JWTs issued by backend (pyotp + python-jose).
- **AI/RAG:** Anthropic Claude API, Claude Agent SDK, Anthropic Python SDK, pgvector (PostgreSQL), OpenAI text-embedding-3-small (1536 dims)
- **Payments:** Credit system (in-app currency), Paystack (mobile money, cards), SMS-based subscriptions (Orange Money, Wave)
- **Deploy:** GitHub Actions → Docker images → ghcr.io → VPS (Traefik reverse proxy), Sentry + PostHog

## Architecture (3-layer)

```
Frontend (Next.js 15 PWA) → Backend (FastAPI + PostgreSQL + Redis) → AI/RAG (Claude API + pgvector + embeddings)
```

Key architectural decisions:
- **Multi-course RAG:** Each course has its own uploaded documents (PDF/CSV/Word) indexed into 512-token chunks with embeddings in pgvector. No fixed reference books — any content can be a course source.
- No LangChain/LlamaIndex — Claude Agent SDK + Anthropic Python SDK called directly
- Content (lessons, quizzes, flashcards, case studies) is generated on first access then cached in `generated_content` table
- **Dynamic taxonomy:** Domains, levels, and audience types are admin-managed via DB lookup tables, not hardcoded enums
- **Curricula:** Ordered collections of courses with public/private visibility and granular access control (users/groups)
- **Expert marketplace:** Experts create courses, set credit prices, earn revenue from enrollments
- Adaptive testing uses CAT algorithm; flashcard scheduling uses FSRS spaced repetition
- All AI-generated content includes source citations back to course reference materials
- PostgreSQL Row Level Security (RLS) for data isolation

## Key Design Constraints

- **Offline-first:** Must work on 2G/3G, TTI <3s on 3G, JS bundle <150KB gzipped. Last accessed course modules downloadable for offline use (IndexedDB). Content downloaded on-demand only (save mobile data). Progression syncs when back online via background sync.
- **Bilingual:** All UI and generated content in FR/EN with instant switching via next-intl
- **Context-aware:** Content adapts to user's country and language preference
- **Mobile-first:** Responsive from 320px, 44×44px touch targets, WCAG 2.1 AA
- **AI latency targets:** P95 <8s for lessons, <5s for quizzes

## Domain Model Overview

The platform uses a dynamic, multi-course architecture. Key entities (see `backend/app/domain/models/`):

- **Course** — Created by admins or experts from uploaded PDFs. Has status (draft/published/archived), visibility, per-course RAG collection, and credit pricing.
- **Module** — Belongs to a course. Contains ordered units (lessons, quizzes, case studies). Prerequisites enforce sequential progression.
- **Curriculum** — Ordered collection of courses. Public or private with user/group access control.
- **Taxonomy** — Admin-managed categories: domain (e.g., health_sciences, engineering, law), level (beginner→expert), audience type (student→professional). Courses tagged with multiple categories.
- **Credit system** — Credit accounts, transactions, packages. Courses can be free or priced in credits. 12 transaction types (purchase, tutor usage, course earning, payout, etc.).
- **Subscription** — SMS-based subscriptions with daily message limits and payment tracking.
- **Marketplace** — Course pricing, star ratings, reviews, expert revenue/commission.
- **User groups** — Groups with membership, used for private curriculum access control.
- **Course resources** — Uploaded PDFs/CSVs/Word docs per course, extracted and indexed for RAG.
- **Generated audio** — TTS audio for lesson content (accessibility).
- **Learner memory** — AI tutor remembers learner context across sessions.

## CRITICAL — Do NOT Re-scaffold

The monorepo is fully built with 62+ Alembic migrations. **DO NOT** recreate, overwrite, or restructure:
- `backend/` — FastAPI with uv (NOT Poetry), directory structure in `.claude/skills/fastapi-service/SKILL.md`
- `frontend/` — Next.js 15 with npm, Tailwind + shadcn/ui, next-intl (FR/EN)
- `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`
- Alembic migrations in `backend/migrations/` (NOT `backend/alembic/`)

When implementing an issue, **build on top of what exists**. Read the existing code first. If a file already exists, edit it — do not create a parallel version.

## Regulatory Compliance

Must align with: GDPR, Senegal Loi 2008-12, Ghana Data Protection Act 2012, Nigeria NDPR 2019, Côte d'Ivoire Loi n°2013-450. Claude API keys must remain server-side only.

## Current State & Roadmap

### Built (production)
- Auth (TOTP MFA, magic link recovery, JWT)
- Multi-course system (admin CRUD, AI-generated syllabi from uploaded PDFs, publish/archive)
- Curricula (ordered course collections, public/private, user/group access)
- Admin panels (courses, curricula, taxonomy, groups, users, analytics, audit logs, payments, settings)
- Learning features (lessons, quizzes, flashcards, case studies, summative assessments, placement tests)
- AI tutor (RAG-based chat with source citations, learner memory, daily limits)
- Expert marketplace (course creation, pricing, reviews, revenue dashboard)
- Credit system (accounts, packages, transactions, generation cost tracking)
- Subscriptions (SMS-based, daily limits, payment tracking)
- Offline-first PWA (module download, offline rendering, background sync)
- Lesson audio generation (TTS for accessibility)

### Future / aspirational
- DHIS2/DHS/WHO/PubMed live data integration
- Pyodide Python/R sandbox for exercises
- Native mobile apps (iOS/Android)
- SCORM/LMS integration
- Video and live courses
- Official certifications (PDF + badges)
