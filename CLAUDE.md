# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SantePublique AOF** — an adaptive, bilingual (FR/EN), mobile-first learning platform for public health professionals in West Africa. Uses AI (Claude API + RAG) to generate personalized content from 3 reference textbooks and real African health data (DHIS2, DHS, WHO AFRO).

**Current status:** Phase 0 scaffolding complete. Monorepo with `backend/` (FastAPI) and `frontend/` (Next.js 15) fully initialized. Backend has health endpoints with tests passing. Frontend has App Router with FR/EN i18n, Tailwind + shadcn/ui, and mobile-first navigation. Docker Compose, CI/CD, and Alembic are configured. Next: DB schema migrations, Supabase Auth, RAG pipeline.

## Planned Tech Stack

- **Frontend:** Next.js 15 + React 19, Tailwind CSS + shadcn/ui, Zustand, TanStack Query, next-intl (i18n), next-pwa + Workbox (offline/PWA)
- **Backend:** FastAPI (Python 3.12), PostgreSQL 16 (Supabase), Redis 7, Celery
- **Auth:** Supabase Auth (email, Google/LinkedIn OAuth, JWT + refresh tokens)
- **AI/RAG:** Anthropic Claude 3.5 Sonnet, Anthropic Python SDK, pgvector (PostgreSQL), OpenAI text-embedding-3-small
- **Deploy:** GitHub Actions + Docker, Fly.io or Railway, Cloudflare Workers (CDN), Sentry + PostHog

## Architecture (4-layer)

```
Frontend (Next.js/React PWA) → Backend (FastAPI + Supabase) → AI/RAG (Claude + pgvector) → External Data (DHIS2, DHS, WHO, PubMed)
```

Key architectural decisions:
- RAG pipeline indexes 3 reference PDFs into 512-token chunks with embeddings in pgvector (PostgreSQL)
- No LangChain/LlamaIndex — Anthropic Python SDK called directly for simplicity
- Content (lessons, quizzes, flashcards, case studies) is generated on first access then cached in `generated_content` table
- Adaptive testing uses CAT algorithm; flashcard scheduling uses FSRS spaced repetition
- Pyodide runs Python/R in-browser for biostatistics exercises
- All AI-generated content includes source citations back to reference materials
- PostgreSQL Row Level Security (RLS) for data isolation

## Key Design Constraints

- **Offline-first:** Must work on 2G/3G, TTI <3s on 3G, JS bundle <150KB gzipped
- **Bilingual:** All UI and generated content in FR/EN with instant switching via next-intl
- **Country-contextualized:** Lessons adapt to user's ECOWAS country using real health data
- **Mobile-first:** Responsive from 320px, 44×44px touch targets, WCAG 2.1 AA
- **AI latency targets:** P95 <8s for lessons, <5s for quizzes

## Curriculum Structure

4 progressive levels, 15 modules, ~320 hours total:
- **Level 1 (Beginner, 60h):** M01-M03 — Foundations, health data intro, West African health systems
- **Level 2 (Intermediate, 90h):** M04-M07 — Epidemiology, surveillance, DHIS2, biostatistics
- **Level 3 (Advanced, 100h):** M08-M12 — Advanced stats/epi, health programming, data viz
- **Level 4 (Expert, 70h):** M13-M15 — Policy, health systems strengthening, research capstone

## Regulatory Compliance

Must align with: GDPR, Senegal Loi 2008-12, Ghana Data Protection Act 2012, Nigeria NDPR 2019, Côte d'Ivoire Loi n°2013-450. Claude API keys must remain server-side only.

## Development Roadmap

- **Phase 0 (2 weeks):** Infrastructure, CI/CD, DB schema, RAG indexing pipeline
- **Phase 1 (6 weeks):** MVP — Auth, Dashboard, M01-M03, basic quiz/flashcards
- **Phase 2 (8 weeks):** DHIS2 integration, case studies, Python sandbox, AI tutor
- **Phase 3-6:** Spaced repetition, remaining modules, certifications, native apps
