---
name: react-components
description: Build React components for the Sira learning platform. Use when creating or modifying React/TypeScript components. Enforces Tailwind CSS + shadcn/ui, mobile-first responsive design, offline-ready PWA patterns, accessibility, and FR/EN i18n.
user-invocable: true
---

# Sira React Component Builder

Build production-grade React 19 components for Sira — a mobile-first, bilingual (FR/EN), multi-course learning platform for learners and professionals, with a mobile-first focus on West Africa.

## Before writing any component

1. Check if a similar component already exists in the `components/` directory
2. Check shadcn/ui for a base component to extend (do not reinvent primitives)
3. Confirm the component works at 320px width (mobile-first)

## Technology constraints (non-negotiable)

- **Framework**: Next.js 15 App Router + React 19
- **Language**: TypeScript 5.x (strict mode)
- **Styling**: Tailwind CSS + shadcn/ui components
- **State**: Zustand for client state, TanStack Query v5 for server state
- **Forms**: React Hook Form + Zod validation
- **i18n**: next-intl (every user-facing string must use `useTranslations()` or `getTranslations()`)
- **PWA**: next-pwa + Workbox (offline-first caching)
- **A11y**: WCAG 2.1 Level AA compliance

## FORBIDDEN patterns — do NOT use

- CSS Modules or plain CSS files (use Tailwind only)
- Any other component library besides shadcn/ui (no MUI, Ant, Chakra)
- Redux (use Zustand for client state, TanStack Query for server state)
- Hardcoded French or English strings (use `t('key')` from next-intl)
- Hardcoded hex/rgb colors (use Tailwind design tokens)
- `px` units for spacing (use Tailwind spacing scale)
- Inline styles
- `any` type in TypeScript

## Component template

```tsx
'use client'; // Only if component needs interactivity

import { useTranslations } from 'next-intl';

interface ComponentNameProps {
  // Explicit typed props
}

export function ComponentName({ ...props }: ComponentNameProps) {
  const t = useTranslations('ComponentScope');

  return (
    <div className="flex flex-col gap-4">
      {/* Use t('key') for all text */}
    </div>
  );
}
```

## Mobile-first responsive design (critical)

This platform targets users on Android mid-range phones with 3G connections.

- **Design mobile-first**: start at 320px, scale up
- **Breakpoints**: `sm:` (640px), `md:` (768px), `lg:` (1024px), `xl:` (1280px)
- **Touch targets**: minimum 44×44px (`min-h-11 min-w-11`)
- **Font size**: minimum 16px on mobile (prevents iOS zoom on input focus)
- **Bottom navigation**: on mobile, top sidebar on desktop
- **Swipe gestures**: for flashcards, lesson navigation
- **Readable in sunlight**: high contrast, large text options

```tsx
// Mobile-first responsive pattern
<div className="flex flex-col md:flex-row gap-4">
  <aside className="hidden md:block w-60">
    {/* Desktop sidebar */}
  </aside>
  <main className="flex-1 px-4 md:px-6">
    {/* Content */}
  </main>
  <nav className="fixed bottom-0 left-0 right-0 md:hidden bg-white border-t">
    {/* Mobile bottom navigation */}
  </nav>
</div>
```

## Learning-specific components

### Course catalog
- Card grid layout (1 col mobile, 2 col tablet, 3 col desktop)
- Each card: title (FR/EN), domain/level/audience badges (color-coded), estimated hours, module count, cover image
- "Enroll" button (or "Enrolled" badge if already enrolled)
- Pill chip filter bar: filter by domain(s), level(s), audience type(s) — horizontally scrollable on mobile
- Taxonomy endpoint: `GET /api/v1/courses/taxonomy` returns enum values with FR/EN labels
- URL search params for shareable filter state, "Clear filters" button
- API: `GET /api/v1/courses?course_domain=X&course_level=Y&audience_type=Z`, `POST /api/v1/courses/{id}/enroll`
- Taxonomy arrays: course_domain[], course_level[], audience_type[] — each course can have multiple values

### Admin course management
- Table view: all courses with status badge (draft/published/archived) and taxonomy badges
- Create/edit course dialog: title FR/EN, domain(s)/level(s)/audience(s) via MultiSelectChips, hours, cover image
- Publish/archive action buttons with confirmation dialog
- "Generate Structure" button: calls AI agent, shows loading, displays generated modules
- API: `GET/POST /api/v1/admin/courses`, publish/archive/generate-structure endpoints

### Lesson viewer
- Stream AI-generated content via SSE (show skeleton while loading)
- Bilingual term highlights: tap to see FR↔EN translation
- Source citations at bottom: "Source: Donaldson Ch.3, p.45"
- Progress indicator: reading progress bar at top

### Quiz component
- One question per screen on mobile
- Large touch-friendly answer buttons (full width, min 44px height)
- Immediate feedback: green/red flash + explanation
- Progress: "Question 3/10" with progress bar
- Timer optional (shown but not enforced for formative quizzes)

### Flashcard deck
- Swipe left/right or tap buttons for FSRS rating
- Card flip animation (front: term, back: definition + example)
- Bilingual: show term in primary language, definition in both
- "Due today" counter badge
- Session summary: cards reviewed, accuracy

### Progress dashboard
- Module map: modules from enrolled course(s) with lock/progress/complete status
- Circular progress rings per module
- Daily streak counter with flame icon
- Next review schedule (from FSRS)
- Recommended next action

### AI Tutor chat
- Chat bubble interface (user right, AI left)
- Streaming response display (word by word)
- Source citations inline: clickable links to reference material
- "50 messages remaining today" counter
- Suggested questions as quick-reply chips

## Offline-first patterns (critical for 2G/3G)

```tsx
// Use TanStack Query with offline persistence
import { useQuery } from '@tanstack/react-query';

function useModule(moduleId: string) {
  return useQuery({
    queryKey: ['module', moduleId],
    queryFn: () => fetchModule(moduleId),
    staleTime: 24 * 60 * 60 * 1000, // 24h — content rarely changes
    gcTime: 7 * 24 * 60 * 60 * 1000, // Keep in cache 7 days
  });
}
```

- Cache last-accessed module content for offline use
- Flashcards: pre-fetch today's due cards on app open
- Queue quiz submissions when offline, sync when back online
- Show clear offline indicator in UI
- Optimistic updates for quiz answers and flashcard ratings

## Performance (non-negotiable)

- JS bundle: <150KB gzipped initial load
- TTI: <3s on simulated 3G (Moto G4)
- Lazy load heavy components (sandbox, charts)
- Use `next/image` with appropriate sizing for all images
- Prefer Server Components; use `'use client'` only when needed

## Billing & Marketplace components

### Credit balance widget
```tsx
// components/billing/CreditBalanceWidget.tsx
// Compact widget showing current credit balance — used in header/sidebar
// Props: balance (number), showTopUpLink (boolean)
// Shows: coin icon + formatted balance + optional "Top up" link
// Color: amber/gold (--color-accent) for balance amount
// Updates optimistically on credit deduction
```

### Marketplace components
```tsx
// components/marketplace/PriceBadge.tsx
// Displays course price in credits or "Free"
// Props: priceCredits (number), isFree (boolean)
// Free: green badge "Gratuit / Free"
// Paid: amber badge "X crédits"
// Must use t('marketplace.free') and t('marketplace.credits', { count: X })

// components/marketplace/StarRating.tsx
// Read-only or interactive star rating (1–5)
// Props: rating (number), reviewCount (number), interactive (boolean), onChange (fn)
// Uses filled/empty star icons, aria-label for accessibility
// Minimum touch target 44×44px on interactive variant

// components/marketplace/PurchaseDialog.tsx
// shadcn Dialog confirming credit purchase of a course
// Shows: course title, price in credits, current balance, post-purchase balance
// CTA: "Confirm purchase" — calls POST /api/v1/marketplace/{courseId}/purchase
// Error state: insufficient credits → link to /billing/topup
// Loading state during API call
```

### Expert dashboard components
```tsx
// components/expert/EnrollmentChart.tsx
// Simple bar or line chart: enrollments over time for a course
// Lazy-loaded (dynamic import) to keep initial bundle small
// Uses native SVG or recharts (check if already in package.json first)

// components/expert/RevenueCard.tsx
// Card showing total credits earned, this month's earnings, payout status
// Props: totalCredits, monthCredits, payoutStatus
// Color: gold/amber accent for revenue figures

// components/expert/CourseAnalyticsTable.tsx
// Table: course title, enrollments, avg rating, revenue, status badge
// Sortable columns, mobile-friendly (horizontal scroll on small screens)
```

## Accessibility (WCAG 2.1 AA)

- All interactive elements keyboard-navigable
- `aria-label` on icon-only buttons
- Color contrast ≥ 4.5:1 for text, ≥ 3:1 for large text
- Focus visible indicators on all interactive elements
- Screen reader support (VoiceOver, TalkBack)
- `role` and `aria-*` attributes on custom components
- shadcn/ui components are accessible by default — leverage them

## Billing Components (`components/billing/`)

- **`balance-widget.tsx`** — Credit balance display for sidebar/header. Shows current balance, low balance warning. Clickable → navigate to purchase page.
- **`purchase-card.tsx`** — Credit package card: name, credits, price. Select → confirm dialog.
- **`insufficient-balance-modal.tsx`** — Triggered on 402 response. Shows balance, required amount, CTA to buy credits. Reusable across all content pages.

## Expert Components (`components/expert/`)

- **`expert-guard.tsx`** — Role gate: checks JWT for role=expert or admin. Redirects non-experts.
- **`expert-nav.tsx`** — Tab navigation: Overview, My Courses, Revenue, Credits.
- **`course-card.tsx`** — Expert's course card with status badge, enrollment count, revenue.
- **`revenue-chart.tsx`** — Monthly revenue bar chart (gross, commission, net).
- **`credit-balance.tsx`** — Credit balance widget for expert dashboard.
- **`cost-estimator.tsx`** — Client-side course generation cost estimator. Uses pdf.js to read page count from selected PDFs without uploading. Calculates estimated credits for embedding, structure, lessons, quizzes, flashcards. Shows breakdown + balance comparison. Rates fetched from `GET /api/v1/billing/generation-rates`.

## Marketplace Components (`components/marketplace/`)

- **`course-grid.tsx`** — Responsive grid of marketplace courses (1/2/3 columns).
- **`marketplace-card.tsx`** — Course card: title, price badge, rating, expert avatar.
- **`price-badge.tsx`** — "Free" or "X credits" badge with appropriate styling.
- **`star-rating.tsx`** — Star rating display (read-only) and input (interactive). 1-5 stars.
- **`review-card.tsx`** — Individual review: rating stars, comment, user name, date.
- **`purchase-dialog.tsx`** — Purchase confirmation: price, current balance, balance after. Confirm/cancel.
- **`review-form.tsx`** — Star rating selector + comment textarea. Submit review.
- **`expert-bio.tsx`** — Expert info section: name, avatar, course count.
