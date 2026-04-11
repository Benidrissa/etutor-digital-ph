---
name: ui-design
description: Design and review UI layouts for the Sira learning platform. Use when planning page layouts, reviewing designs, or making visual decisions. Enforces the education design system with green/gold palette, mobile-first, offline indicators, and learning UX patterns.
user-invocable: true
---

# Sira UI Design System

Design interfaces for Sira — a mobile-first, bilingual, multi-course learning platform for learners and professionals across West African countries and beyond.

## Design philosophy

This is a **learning tool for professionals and students**, not a consumer social app. The UI must communicate:
- **Trust** — educational authority, professional credibility
- **Clarity** — content readability above all, even in bright sunlight
- **Accessibility** — works on low-end Android phones, 320px screens, slow connections
- **Progress** — learners must always see where they are and what's next
- **Calm** — reduce cognitive load; the learning content is already dense

## Color system (knowledge + Africa identity)

Palette inspired by growth/knowledge (green) and West African identity (gold/earth):

```css
/* Primary — knowledge, trust, progress */
--color-primary:          #0F766E;   /* Teal green — growth/knowledge */
--color-primary-dark:     #115E59;
--color-primary-light:    #14B8A6;
--color-primary-50:       #F0FDFA;   /* Very light tint for backgrounds */

/* Accent — Africa, warmth, achievement */
--color-accent:           #D97706;   /* Gold/amber — achievement, Africa */
--color-accent-dark:      #B45309;
--color-accent-light:     #FDE68A;
--color-accent-50:        #FFFBEB;

/* Neutrals — text, borders, surfaces */
--color-text-primary:     #1C1917;   /* Stone 900 */
--color-text-secondary:   #57534E;   /* Stone 600 */
--color-text-muted:       #A8A29E;   /* Stone 400 */
--color-border:           #E7E5E4;   /* Stone 200 */
--color-border-strong:    #D6D3D1;   /* Stone 300 */
--color-surface:          #FFFFFF;
--color-surface-raised:   #FAFAF9;   /* Stone 50 */
--color-surface-sunken:   #F5F5F4;   /* Stone 100 */

/* Status — learning states */
--color-success:          #16A34A;   /* Correct answer, module complete */
--color-success-light:    #DCFCE7;
--color-warning:          #D97706;   /* Needs attention, due reviews */
--color-warning-light:    #FEF3C7;
--color-danger:           #DC2626;   /* Wrong answer, failed quiz */
--color-danger-light:     #FEE2E2;
--color-info:             #2563EB;   /* In progress, informational */
--color-info-light:       #DBEAFE;

/* Learning-specific */
--color-streak:           #F59E0B;   /* Daily streak flame */
--color-locked:           #D6D3D1;   /* Locked module */
```

Map these to Tailwind config via `tailwind.config.ts` — use Tailwind classes, not raw CSS variables.

## Typography

- Primary font: Inter (400, 500, 600)
- Monospace: JetBrains Mono (code sandbox, statistics formulas)
- Minimum 16px body text on mobile (prevents iOS zoom)
- Scale: 14px / 16px / 18px / 20px / 24px / 30px / 36px
- Line height: 1.5 for body, 1.25 for headings
- High contrast for outdoor readability

## Layout rules — mobile-first

- **Mobile (320–767px)**: single column, bottom nav, full-width cards
- **Tablet (768–1023px)**: optional sidebar, 2-column where useful
- **Desktop (1024–1440px)**: sidebar nav, wider content area
- Padding: 16px (mobile), 24px (tablet+)
- Max content width: 768px for reading content (optimal line length)
- Touch targets: minimum 44×44px

### Mobile navigation
```
┌────────────────────────┐
│ [←] Module 3 / Unit 2  │  ← Top bar with breadcrumb
├────────────────────────┤
│                        │
│   (Content area)       │
│                        │
├────────────────────────┤
│ 🏠  📚  🃏  🤖  ⚙️  │  ← Bottom nav (Dashboard, Modules, Cards, Tutor, Settings)
└────────────────────────┘
```

### Desktop navigation
```
┌──────┬─────────────────┐
│      │ Breadcrumb       │
│ Side │─────────────────│
│ bar  │                  │
│ nav  │ (Content area)   │
│      │                  │
└──────┴─────────────────┘
```

## Learning-specific design patterns

### Course catalog
- Card grid: 1 col (mobile) → 2 col (tablet) → 3 col (desktop)
- Each card: cover image (or domain-colored gradient fallback), title, domain badge, duration, module count
- "Enroll" CTA button (primary) or "Enrolled" badge (success green)
- Filter row: domain dropdown + search input
- Empty state: "No courses match your search"

### Admin course management
- Table layout: title, status badge (draft=gray, published=green, archived=orange), module count, created date
- Actions column: publish/archive/delete buttons
- Create dialog: shadcn Dialog with form (title FR/EN, domain, hours, cover image URL)
- Generate structure: loading spinner → generated module list with checkmarks

### Module map (dashboard)
- Grid of module cards from enrolled course(s): number, title, status icon, progress ring
- States: locked (gray, lock icon), in-progress (primary, progress %), completed (green, check)
- Prerequisite lines connecting dependent modules
- Current streak prominently displayed

### Lesson viewer
- Clean reading layout, max 768px width
- Progress bar at top (thin, primary color)
- Bilingual term highlights: tap to toggle FR↔EN
- Source citations: subtle, at section end
- "Continue" button fixed at bottom on mobile

### Quiz interface
- One question per screen on mobile
- Large answer buttons: full width, min 48px height, clear padding
- After answer: green/red background flash → explanation card
- Progress: "3/10" with thin progress bar
- Summary screen with score, time, weak areas

### Flashcard deck
- Card centered, max 400px width
- Tap to flip (front → back)
- Swipe or 4 rating buttons below: Again / Hard / Good / Easy
- "Due today: 12 cards" counter
- Session summary when deck complete

### AI Tutor chat
- Chat bubbles: user (right, primary tint), AI (left, surface-raised)
- Streaming indicator: 3 animated dots
- Source chips below AI messages: clickable reference links
- Quick-reply suggestions above input
- Daily message counter: "42/50 messages today"

### Progress indicators
- Circular progress ring for module completion
- Linear progress bar for lesson/quiz progress
- Streak flame with day count
- Calendar heat map for review consistency

## What to design (correct patterns)

- **Course catalog**: Card grid with enroll buttons, domain filters, search
- **Admin courses**: Table + create dialog + publish/archive actions
- **Dashboard**: Module grid with progress + streak counter + review reminder
- **Lists**: Clean card lists with clear hierarchy, not dense data tables
- **Login**: Simple form, language selector, no hero section
- **Navigation**: Bottom bar (mobile) / sidebar (desktop), clear active state
- **Cards**: Subtle border or shadow-sm, rounded-lg
- **Buttons**: rounded-md (6px), solid primary color, min 44px height
- **Loading**: Skeleton loaders with animate-pulse during AI generation
- **Success**: Confetti-free — just a green check + congratulations text

## What NEVER to design (banned patterns)

- Dense data tables for learning content (use cards)
- Tiny text or touch targets below 44px
- Desktop-only layouts without mobile consideration
- Animations that consume battery or data
- Gradient overload or glassmorphism effects
- Complex multi-step wizards (keep flows short)
- Auto-playing video or audio

## Dark mode

Support dark mode for:
- Battery saving on OLED screens (common on mid-range Android)
- Evening study sessions
- Map all color tokens to dark equivalents in Tailwind config

## Offline indicator

Always show a clear but non-intrusive offline banner:
```
┌────────────────────────────────┐
│ 📡 You are offline — cached   │  ← Yellow banner, dismissible
│    content available           │
└────────────────────────────────┘
```

## Expert dashboard layout

```
Desktop:
┌──────┬──────────────────────────────────────────┐
│ Side │ Expert Dashboard                          │
│ nav  ├──────────────┬───────────────────────────┤
│      │ Revenue card  │ Enrollments card          │
│      │ (gold/amber)  │ (primary teal)            │
│      ├──────────────┴───────────────────────────┤
│      │ My Courses table (title, enrollments,     │
│      │ avg rating ★, revenue, status badge)      │
│      │ [+ New Course] button top-right           │
└──────┴──────────────────────────────────────────┘

Mobile:
- Revenue + Enrollment as stacked summary cards (full-width)
- Course list as card list (not table)
- FAB (+) button bottom-right for new course
```

Design rules:
- Revenue figures in gold/amber (`text-amber-600`) — expert motivation
- Status badge colors: draft=gray, review=blue, published=green, archived=orange
- Analytics charts: lazy-loaded, skeleton placeholder while loading

## Marketplace browse/detail layout

### Browse page
```
┌────────────────────────────┐
│ Search bar                 │  ← sticky on mobile
│ [Domain ▼] [Level ▼] [Free/Paid ▼] │
├────────────────────────────┤
│ [Course card]  [Course card] │  ← 1 col mobile, 2 col tablet, 3 col desktop
│   Cover image                │
│   Title                      │
│   ★★★★☆ (4.2) · 128 enrolls │
│   PriceBadge: "Free" / "50 crédits" │
│   [Enroll] / [Purchase]      │
└────────────────────────────┘
```

### Course detail page
```
┌────────────────────────────┐
│ Cover image (16:9)         │
├────────────────────────────┤
│ Title                      │
│ By [Expert name]           │
│ ★★★★☆ 4.2 (45 reviews)    │
│ PriceBadge + [Purchase CTA]│ ← sticky on mobile
├────────────────────────────┤
│ Description                │
│ What you'll learn (bullets)│
├────────────────────────────┤
│ Reviews section            │
│  [★★★★★] "Great course..." │
│  [Load more]               │
└────────────────────────────┘
```

Design rules:
- PriceBadge: green pill for "Free", amber pill for paid
- Purchase CTA: sticky at bottom on mobile (44px height minimum)
- Star rating: filled amber stars (`text-amber-400`)
- "Enrolled" state: CTA becomes green "Access Course" button

## Billing/purchase page layout

### Credit wallet page (`/billing`)
```
┌────────────────────────────┐
│ Credit Balance             │
│  ◎ 250 crédits             │  ← large, amber/gold
│  [+ Top up credits]        │
├────────────────────────────┤
│ Recent transactions        │
│  + 100   Top-up  Jan 15    │
│  - 5     Lesson gen  Jan 14│
│  - 50    Course purchase   │
│  [View all]                │
└────────────────────────────┘
```

### Top-up / purchase flow
```
┌────────────────────────────┐
│ Buy Credits                │
│                            │
│  [50 credits — $5]         │  ← option cards (select one)
│  [100 credits — $9]  ✓     │
│  [200 credits — $16]       │
│                            │
│  [Continue to payment →]   │
└────────────────────────────┘
```

Design rules:
- Credit amount: large amber text, coin icon (`◎`)
- Deduction transactions: red (`text-red-600`), top-ups: green (`text-green-600`)
- Option cards: bordered, selected state with primary teal border + check
- Purchase confirmation dialog before any credit deduction

## Page review checklist

When reviewing any UI design or implementation:
1. Does it work at 320px width? (Test first)
2. Are ALL touch targets ≥ 44×44px?
3. Is ALL text internationalized (FR/EN via next-intl)?
4. Is the font size ≥ 16px on mobile?
5. Is color contrast ≥ 4.5:1 (WCAG AA)?
6. Does it work offline with cached content?
7. Does it feel like a learning platform or a SaaS dashboard?
8. Is the reading experience comfortable for 15-minute sessions?
9. Are loading states clear during AI content generation?
