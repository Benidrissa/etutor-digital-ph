---
name: testing
description: Write tests for the SantePublique AOF learning platform. Use when creating unit tests, integration tests, or E2E tests. Enforces pytest-asyncio patterns for the FastAPI backend, React Testing Library for frontend, and Playwright for E2E.
user-invocable: true
---

# SantePublique AOF Testing Skill

Write comprehensive tests for the SantePublique AOF backend (FastAPI) and frontend (Next.js/React). Tests must cover learning workflows, AI/RAG content generation, offline behavior, and **mobile-first UX** — this platform targets mid-range Android phones on 2G/3G in West Africa.

## Backend testing (Python/pytest)

### Unit tests — isolate business logic

```python
import pytest
from unittest.mock import AsyncMock

class TestLessonGenerationService:
    """Tests for AI-generated lesson content."""

    async def test_returns_cached_lesson_when_available(self):
        content_repo = AsyncMock()
        content_repo.find_cached.return_value = mock_lesson
        retriever = AsyncMock()
        service = LessonService(content_repo=content_repo, retriever=retriever)

        result = await service.generate_lesson(module_id, unit_id, "fr", "senegal", 1)

        assert result == mock_lesson
        retriever.search.assert_not_called()  # Should NOT hit RAG

    async def test_generates_via_rag_on_cache_miss(self):
        content_repo = AsyncMock()
        content_repo.find_cached.return_value = None
        retriever = AsyncMock()
        retriever.search.return_value = mock_chunks
        generator = AsyncMock()
        generator.generate_lesson.return_value = mock_generated
        service = LessonService(
            content_repo=content_repo, retriever=retriever, generator=generator
        )

        result = await service.generate_lesson(module_id, unit_id, "fr", "senegal", 1)

        retriever.search.assert_called_once()
        generator.generate_lesson.assert_called_once()
        content_repo.save.assert_called_once()
        assert result.sources_cited is not None

    async def test_generated_content_includes_sources(self):
        # Every generated lesson MUST cite reference sources
        ...
        assert len(result.sources_cited) > 0
        assert all("book" in s and "chapter" in s for s in result.sources_cited)
```

**Rules:**
- Mock ALL repositories, HTTP clients (DHIS2, WHO), and AI services (Claude API)
- Test cache-hit and cache-miss paths for all content generation
- Test every public method in domain services
- Verify generated content always includes `sources_cited`
- Test FSRS scheduling calculations independently
- Test CAT algorithm difficulty selection logic

### Integration tests — real database, real HTTP

```python
import pytest
from httpx import AsyncClient, ASGITransport

@pytest.fixture
async def client(app, db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

class TestModuleRoutes:
    async def test_list_modules_returns_200(self, client, auth_headers):
        response = await client.get("/api/v1/modules", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/v1/modules")
        assert response.status_code == 401

    async def test_module_progress_respects_prerequisites(self, client, auth_headers):
        # Module 4 locked if Module 3 not completed at 80%
        response = await client.get("/api/v1/modules/4", headers=auth_headers)
        assert response.json()["status"] == "locked"

class TestQuizRoutes:
    async def test_submit_quiz_returns_score(self, client, auth_headers):
        response = await client.post(
            "/api/v1/quizzes/submit",
            json={"quiz_id": str(quiz_id), "answers": mock_answers},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert "score" in response.json()

    async def test_rate_limit_tutor_messages(self, client, auth_headers):
        # Free tier: 50 messages/day
        for _ in range(50):
            await client.post("/api/v1/tutor/message", json=msg, headers=auth_headers)
        response = await client.post("/api/v1/tutor/message", json=msg, headers=auth_headers)
        assert response.status_code == 429
```

**Rules:**
- Use real PostgreSQL (Docker Compose test DB), NOT mocks
- Test every documented endpoint
- Always test 401 (no auth)
- Verify response shapes match API schemas
- Test rate limiting on AI endpoints
- Test prerequisite/unlock logic for modules

### conftest.py pattern

```python
import pytest
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
async def db_session(engine):
    async with AsyncSession(engine) as session:
        yield session
        await session.rollback()

@pytest.fixture
def auth_headers():
    token = create_test_supabase_jwt(user_id="test-user", language="fr", country="senegal")
    return {"Authorization": f"Bearer {token}"}
```

## Frontend testing

### Component tests (Vitest + React Testing Library)

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FlashcardDeck } from './FlashcardDeck';

describe('FlashcardDeck', () => {
  it('displays card front initially', () => {
    render(<FlashcardDeck cards={[mockCard]} />);
    expect(screen.getByText(mockCard.term_fr)).toBeInTheDocument();
  });

  it('flips card on tap', async () => {
    render(<FlashcardDeck cards={[mockCard]} />);
    await userEvent.click(screen.getByRole('button', { name: /flip/i }));
    expect(screen.getByText(mockCard.definition_en)).toBeInTheDocument();
  });

  it('shows FSRS rating buttons after flip', async () => {
    render(<FlashcardDeck cards={[mockCard]} />);
    await userEvent.click(screen.getByRole('button', { name: /flip/i }));
    expect(screen.getByRole('button', { name: /again/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /good/i })).toBeInTheDocument();
  });

  it('displays due count', () => {
    render(<FlashcardDeck cards={mockCards} dueCount={12} />);
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});
```

### i18n testing

```typescript
import { render, screen } from '@testing-library/react';
import { NextIntlClientProvider } from 'next-intl';

function renderWithI18n(component: React.ReactNode, locale = 'fr') {
  const messages = locale === 'fr' ? frMessages : enMessages;
  return render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      {component}
    </NextIntlClientProvider>
  );
}

it('renders in French by default', () => {
  renderWithI18n(<Dashboard />);
  expect(screen.getByText('Tableau de bord')).toBeInTheDocument();
});

it('renders in English when locale is en', () => {
  renderWithI18n(<Dashboard />, 'en');
  expect(screen.getByText('Dashboard')).toBeInTheDocument();
});
```

### Mobile-first E2E tests (Playwright)

All E2E tests MUST run against a mobile viewport by default. This platform targets mid-range Android phones (Moto G4, Samsung A series) on 3G.

#### Playwright config (mandatory)

```typescript
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  projects: [
    {
      name: 'Mobile Chrome',
      use: { ...devices['Moto G4'] },  // PRIMARY — test this first
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
    },
    {
      name: 'Desktop Chrome',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 720 } },
    },
  ],
});
```

#### Mobile-specific test rules
- **Default viewport**: 360×640 (Moto G4) — every test must pass here first
- **Touch targets**: verify all interactive elements are ≥ 44×44px
- **Bottom navigation**: test that mobile nav is visible and functional at <768px
- **Swipe gestures**: test flashcard swiping on touch viewports
- **Font size**: verify no text below 16px on mobile
- **Orientation**: test portrait (primary) and landscape
- **3G throttling**: use `page.route()` or Playwright network throttling for slow connection tests
- **Viewport resize**: test that layouts adapt correctly between mobile/tablet/desktop breakpoints

```typescript
import { test, expect } from '@playwright/test';

// Mobile viewport test helper
test.use({ viewport: { width: 360, height: 640 } });

test('bottom navigation visible on mobile', async ({ page }) => {
  await page.goto('/fr/dashboard');
  await expect(page.getByRole('navigation', { name: /bottom/i })).toBeVisible();
});

test('touch targets are at least 44x44px', async ({ page }) => {
  await page.goto('/fr/modules/m01/quiz/q1');
  const buttons = page.getByRole('button');
  for (const button of await buttons.all()) {
    const box = await button.boundingBox();
    expect(box!.width).toBeGreaterThanOrEqual(44);
    expect(box!.height).toBeGreaterThanOrEqual(44);
  }
});

test('flashcard swipe works on touch viewport', async ({ page }) => {
  await page.goto('/fr/flashcards');
  const card = page.getByTestId('flashcard');
  // Simulate swipe right (= "Good" rating)
  await card.dispatchEvent('pointerdown', { position: { x: 50, y: 200 } });
  await card.dispatchEvent('pointermove', { position: { x: 300, y: 200 } });
  await card.dispatchEvent('pointerup', { position: { x: 300, y: 200 } });
  await expect(page.getByTestId('card-front')).toBeVisible(); // Next card
});
```

### E2E learning flow tests

```typescript
import { test, expect } from '@playwright/test';

test('complete a quiz flow', async ({ page }) => {
  await page.goto('/fr/modules/m01/quiz/q1');
  // Answer questions
  await page.getByRole('button', { name: /option a/i }).click();
  await page.getByRole('button', { name: /suivant/i }).click();
  // ... answer remaining questions
  // Verify score screen
  await expect(page.getByText(/score/i)).toBeVisible();
});

test('flashcard review session', async ({ page }) => {
  await page.goto('/fr/flashcards');
  // Flip card
  await page.getByRole('button', { name: /retourner/i }).click();
  // Rate card
  await page.getByRole('button', { name: /bien/i }).click();
  // Verify next card shown
  await expect(page.getByTestId('card-front')).toBeVisible();
});

test('language switching', async ({ page }) => {
  await page.goto('/fr/dashboard');
  await expect(page.getByText('Tableau de bord')).toBeVisible();
  await page.getByRole('button', { name: /en/i }).click();
  await expect(page.getByText('Dashboard')).toBeVisible();
});
```

### Accessibility testing

```typescript
import { axe } from 'jest-axe';

it('has no accessibility violations', async () => {
  const { container } = render(<QuizQuestion question={mockQuestion} />);
  const results = await axe(container);
  expect(results).toHaveNoViolations();
});
```

### Offline testing

```typescript
test('shows offline indicator when disconnected', async ({ page, context }) => {
  await page.goto('/fr/dashboard');
  await context.setOffline(true);
  await expect(page.getByText(/hors ligne/i)).toBeVisible();
});

test('queues quiz submission when offline', async ({ page, context }) => {
  await page.goto('/fr/modules/m01/quiz/q1');
  await context.setOffline(true);
  // Submit quiz answer
  await page.getByRole('button', { name: /option a/i }).click();
  // Should show queued indicator, not error
  await expect(page.getByText(/en attente/i)).toBeVisible();
});
```

## Coverage requirements

- Unit tests: ≥80% coverage on business logic (services, algorithms)
- Every API endpoint has at least one integration test
- Auth tests (401) for every protected endpoint
- AI content generation: test cache-hit and cache-miss paths
- FSRS and CAT algorithms: comprehensive unit tests with known inputs/outputs
- i18n: verify both FR and EN render for key components
- Offline: E2E tests for offline behavior
- **Mobile-first**: all E2E tests must pass on Moto G4 viewport (360×640) before desktop
- **Touch targets**: verify ≥44×44px on interactive elements in key screens
- **Performance**: Lighthouse CI check for TTI <3s on simulated 3G

## Running tests

```bash
# Backend (from backend/)
pytest                        # All tests
pytest tests/unit/            # Unit only
pytest tests/integration/     # Integration only
pytest --cov                  # With coverage

# Frontend (from frontend/)
npm test                      # Vitest
npx playwright test           # E2E
```
