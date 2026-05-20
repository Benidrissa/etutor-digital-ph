# Staging tutor smoke test

A 7-step checklist to run after every `Deploy to Server` job lands green
on `main`. Validates the four shipped tutor changes (#1979, #1981, #1985,
#1989) end-to-end and gives a binary go/no-go before promoting to
production via `workflow_dispatch`.

**Time:** ~5 minutes if everything passes, longer if a check fails (then
STOP, file a follow-up).

**Pre-requisites:**

- Sign-in as a learner with at least one module touched (so
  `UserModuleProgress.last_accessed` is populated).
- A short-lived JWT for the API checks. Get one from the browser's
  `localStorage` after sign-in (key `auth_access_token`) and export:
  ```bash
  export TOKEN="<paste-jwt-here>"
  export STAGING_HOST=https://<your-staging-host>   # set per environment
  ```
- SSH access to the staging server (`deploy@167.86.115.58`). The deploy
  workflow at `.github/workflows/deploy.yml:240-280` documents the same
  SSH path.

---

## 1. Anchor badge fires on `/tutor` (#1989)

Navigate to `${STAGING_HOST}/tutor` (bottom nav → AI tutor).

- **Expect:** badge above the chat reading
  *"Tuteur ancré sur: N. <module title>"* with a × dismiss button.
- **Fails if:** no badge → check the endpoint:
  ```bash
  curl -sH "Authorization: Bearer $TOKEN" \
    "$STAGING_HOST/api/v1/tutor/last-module" | jq
  ```
  - `null` → user has no `UserModuleProgress.last_accessed`. Touch any
    module in the UI and reload `/tutor`.
  - 5xx or empty body → endpoint regressed. **STOP**.
  - JSON returned but no badge → frontend `tutor-client.tsx` regression.

---

## 2. Tutor cites unit numbers, not just textbook chapters (#1981, #1989)

In the chat (with the badge present from check #1):

> *Quelles sont les unités du module en cours ?*

- **Expect:** response names units by `unit_number` (e.g.
  *"L'unité 1.2 — Histoire couvre…"*) AND mentions the module by
  name+number (*"Module 1: Fondements de la santé publique"*).
- **Fails if:**
  - *"je ne dispose pas d'une information précise"* → module block is
    empty. Either `_build_current_module_section` is returning `None`
    despite a real `module_id`, or `module.units` isn't populated by
    `selectinload`. **STOP**.
  - Cites only *"Donaldson Ch.X"* without unit numbers → prompt nudge
    isn't taking effect. Check the persona block actually contains
    the *"structure du cours d'abord"* line. **STOP**.

---

## 3. Companion mode quotes generated lessons (#1985)

Pick a unit with generated content (any past unit 1.1; check
`generated_content` table if unsure: `SELECT module_id, content_type,
content->>'unit_id' FROM generated_content WHERE language='fr' LIMIT 5;`).

In the chat:

> *Résume-moi cette leçon.*

- **Expect:** response quotes the actual lesson body — should match
  what's rendered on `/modules/{id}/lessons/...`.
- **Fails if:** tutor improvises generic public-health content →
  either the GeneratedContent query is failing (check server logs for
  *"Failed to load GeneratedContent"*) or the module block is being
  trimmed too aggressively (`tutor-module-content-char-limit`). **STOP**.

---

## 4. Cache telemetry firing — turns 2+ hit cache (#1985)

```bash
ssh deploy@167.86.115.58 \
  'docker logs etutor-backend --tail 200 2>&1 | grep tutor_claude_call | tail -10'
```

- **Expect:** at least one log line per turn from your test session,
  with:
  - **Turn 1**: `cache_creation` populated (≥30 000), `cache_read=0`
  - **Turn 2+**: `cache_read ≥ 30000`, `cache_creation` near zero
- **Fails if:**
  - Every line shows `cache_read=0` → either
    `tutor-context-caching-enabled` got toggled off or
    `_assemble_cached_system` isn't producing the layered list.
    Check the live setting:
    ```bash
    curl -sH "Authorization: Bearer $TOKEN" \
      "$STAGING_HOST/api/v1/admin/settings?key=tutor-context-caching-enabled" | jq
    ```
  - `cache_read` is positive but small (~5 000) → cache key drift.
    `_build_full_module_block` or `_build_course_block` are producing
    different output for the same `(module, language)` inputs across
    turns. **STOP**.

---

## 5. Long-input acceptance (#1989)

In the chat input on staging:

- Paste exactly **5 000 chars** of any text.
- **Expect:** counter shows *"5000 / 16000 characters"* in muted
  foreground; Send button enabled; backend accepts → response streams.
- Paste exactly **16 001 chars**.
- **Expect:** counter turns red; Send disabled.
- **Fails if:**
  - Counter never appears at >12 800 chars (80%) → frontend regressed.
  - Send stays clickable past 16 000 → frontend `canSend` regressed.
  - Backend 422s a 5 000-char message → schema cap regressed
    (`schemas/tutor.py max_length`). **STOP**.

---

## 6. Counter monotonicity (#1979 regression guard)

Note the *"X/Y messages restants aujourd'hui"* counter at the top of
the chat.

- Send 3 short messages back-to-back.
- **Expect:** counter decreases by 3 (Y stays the same), never
  increases.
- **Fails if:** counter ever moves up between turns →
  `_check_daily_limit` regressed (likely back to counting JSON rows
  instead of summing `user_messages_sent`). **STOP**.

(The async-compaction-shouldn't-bump-counter invariant is a long-soak
check — reproducible only past 50 messages. Worth a separate scripted
test if it ever needs to be checked routinely.)

---

## 7. Sidebar count realtime (#1979 regression guard)

In the conversations sidebar (left), pick an existing thread and note
its *"X messages"* count.

- Send a message in that thread.
- **Expect:** the sidebar count bumps to `X+2` (your message + the
  reply) within ~1 second, with no manual refresh.
- **Fails if:** sidebar stays stale → `onMessageSent` callback in
  `chat-panel.tsx` not firing OR `fetchConversations` re-fetch in
  `tutor-client.tsx` not wired. **STOP**.

---

## Decision

- **All 7 pass** → ✅ Safe to promote to production:
  GitHub Actions → Deploy → Run workflow → `environment: production`.
- **Any fail** → **STOP**. File a follow-up issue with:
  - The failing check name + step number from this runbook.
  - The actual response/log line you observed.
  - The commit SHA on `main` you tested against (`git rev-parse main`).

---

## When to update this runbook

Add a check whenever a tutor PR introduces a new invariant that:

1. Could regress silently (no test would catch it but a user would).
2. Has a tractable manual verification (≤30 seconds to check).

Reference convention: add new checks at the bottom and link them back
to the issue/PR that introduced the requirement. Don't reorder existing
checks — operators rely on the numbering.
