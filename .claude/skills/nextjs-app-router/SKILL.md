---
name: nextjs-app-router
description: Build Next.js 15 App Router pages and layouts for the SantePublique AOF learning platform. Use when creating pages, layouts, route handlers, or configuring Next.js features. Enforces server/client component patterns, next-intl, Tailwind, PWA, and mobile-first design.
user-invocable: true
---

# SantePublique AOF Next.js App Router Guide

Build pages and layouts for SantePublique AOF using Next.js 15 App Router conventions.

## Application structure

```
frontend/
├── app/
│   ├── layout.tsx              # Root layout (fonts, providers, PWA manifest)
│   ├── [locale]/
│   │   ├── layout.tsx          # Locale-aware layout (next-intl, sidebar/bottom nav)
│   │   ├── page.tsx            # Landing / marketing page
│   │   ├── (auth)/
│   │   │   ├── login/page.tsx
│   │   │   ├── register/page.tsx
│   │   │   └── placement-test/page.tsx   # Diagnostic assessment
│   │   ├── (app)/                        # Authenticated app shell
│   │   │   ├── layout.tsx                # App layout (nav, offline indicator)
│   │   │   ├── dashboard/page.tsx        # Module map, streak, next reviews
│   │   │   ├── modules/
│   │   │   │   ├── page.tsx              # All modules list
│   │   │   │   └── [moduleId]/
│   │   │   │       ├── page.tsx          # Module overview (units, progress)
│   │   │   │       ├── lessons/
│   │   │   │       │   └── [unitId]/page.tsx  # AI-generated lesson viewer
│   │   │   │       ├── quiz/
│   │   │   │       │   └── [quizId]/page.tsx  # Adaptive quiz
│   │   │   │       ├── flashcards/page.tsx    # Flashcard deck for module
│   │   │   │       └── case-study/page.tsx    # Practical case study
│   │   │   ├── flashcards/page.tsx       # Daily review (all due cards)
│   │   │   ├── tutor/page.tsx            # AI tutor chat
│   │   │   ├── sandbox/page.tsx          # Python/R code sandbox
│   │   │   ├── certificates/page.tsx     # Earned certificates
│   │   │   └── settings/page.tsx         # Profile, language, country
│   │   └── ...
│   └── api/                    # Route handlers (if needed for BFF)
├── components/
│   ├── ui/                     # shadcn/ui components
│   ├── layout/                 # Nav, sidebar, bottom bar, offline indicator
│   ├── learning/               # Lesson viewer, quiz, flashcard, progress
│   └── shared/                 # Common reusable components
├── lib/
│   ├── api.ts                  # FastAPI client (fetch wrapper)
│   ├── store.ts                # Zustand stores
│   └── utils.ts
├── messages/
│   ├── fr.json                 # French translations
│   └── en.json                 # English translations
├── public/
│   └── manifest.json           # PWA manifest
└── next.config.ts
```

## Core conventions

### Server Components (default)
- Pages and layouts are Server Components by default
- Fetch data on the server, pass as props
- Use `async` components for data loading
- Keeps JS bundle small (critical for <150KB target)

### Client Components (opt-in)
- Add `'use client'` only when needed (interactivity, hooks, browser APIs)
- Keep client components small and leaf-level
- Forms, flashcard decks, quiz interactions, chat, sandbox need `'use client'`

### Route Groups
- `(auth)` — unauthenticated pages (login, register, placement test)
- `(app)` — authenticated app shell with navigation and offline support

## i18n with next-intl (mandatory)

Every page uses next-intl for FR and EN:

```tsx
// Server component
import { getTranslations } from 'next-intl/server';

export default async function DashboardPage() {
  const t = await getTranslations('Dashboard');
  return <h1>{t('title')}</h1>;
}

// Client component
'use client';
import { useTranslations } from 'next-intl';

export function ModuleCard() {
  const t = useTranslations('ModuleCard');
  return <span>{t('progress', { percent: 75 })}</span>;
}
```

**NEVER** hardcode French or English strings in components.

Translation files in `messages/fr.json` and `messages/en.json`.

## Data fetching

### Server-side (preferred for initial page load)
```tsx
// In page.tsx (Server Component)
async function getModules(token: string) {
  const res = await fetch(`${API_URL}/api/v1/modules`, {
    headers: { Authorization: `Bearer ${token}` },
    next: { revalidate: 3600 }, // Modules don't change often
  });
  return res.json();
}
```

### Client-side (for interactive updates)
```tsx
'use client';
import { useQuery, useMutation } from '@tanstack/react-query';

function useFlashcardsDue() {
  return useQuery({
    queryKey: ['flashcards', 'due'],
    queryFn: fetchDueFlashcards,
    staleTime: 5 * 60 * 1000, // 5 min
  });
}

function useSubmitQuizAnswer() {
  return useMutation({
    mutationFn: submitAnswer,
    // Optimistic update for offline support
    onMutate: async (answer) => { ... },
  });
}
```

## Streaming AI content (SSE)

For AI-generated lessons and tutor responses, use Server-Sent Events:

```tsx
'use client';

function useLessonStream(moduleId: string, unitId: string) {
  const [content, setContent] = useState('');
  const [isStreaming, setIsStreaming] = useState(true);

  useEffect(() => {
    const eventSource = new EventSource(
      `${API_URL}/api/v1/lessons/${moduleId}/${unitId}/stream`
    );
    eventSource.onmessage = (e) => setContent((prev) => prev + e.data);
    eventSource.onerror = () => { eventSource.close(); setIsStreaming(false); };
    return () => eventSource.close();
  }, [moduleId, unitId]);

  return { content, isStreaming };
}
```

## Styling: Tailwind CSS + shadcn/ui

```tsx
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

<Card className="w-full">
  <CardHeader>
    <CardTitle>{t('moduleTitle')}</CardTitle>
  </CardHeader>
  <CardContent>
    <Button className="w-full min-h-11">{t('startLesson')}</Button>
  </CardContent>
</Card>
```

**FORBIDDEN**: CSS Modules, styled-components, any other component library, inline styles with hardcoded values.

## PWA & Offline

- Configure `next-pwa` with Workbox in `next.config.ts`
- Service Worker caches: app shell, last module, due flashcards
- Show offline indicator banner when navigator.onLine === false
- Queue mutations (quiz submissions, flashcard ratings) for sync when online
- `manifest.json` with app name, icons, theme color

## Navigation patterns

- **Mobile** (< 768px): bottom navigation bar with 4-5 tabs (Dashboard, Modules, Flashcards, Tutor, Settings)
- **Desktop** (≥ 768px): left sidebar navigation
- Breadcrumbs on lesson/quiz pages
- Use Next.js `<Link>` for all internal navigation
- `useRouter()` for programmatic navigation in client components
- Swipe gestures for flashcard navigation on mobile

## Error and loading states

- `error.tsx` boundary per route segment
- `loading.tsx` with skeleton loader (Tailwind animate-pulse)
- AI streaming: show skeleton then progressively render content
- Offline: show cached content with "offline" badge

## Key rules

- Mobile-first: 320px → 1440px responsive
- Touch targets: minimum 44×44px (`min-h-11 min-w-11`)
- Font: minimum 16px on mobile
- All dates: locale-aware formatting (`Intl.DateTimeFormat`)
- Performance: <150KB JS gzipped, TTI <3s on 3G
- Dark mode: support for battery saving on OLED screens
