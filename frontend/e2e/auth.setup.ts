/**
 * Setup project — runs once before persona projects to populate
 * `e2e/.auth/{persona}.json` storage states. Each persona project then loads
 * its file via `storageState` so specs start pre-authed without per-test login
 * round-trips.
 *
 * Strategy:
 *   1. POST /api/v1/auth/login-password (verified working on staging
 *      against e2e-* fixtures from issue #2109).
 *   2. Open the app once so localStorage gets origin-bound.
 *   3. Inject access_token + refresh_token + user object into localStorage
 *      (the FE expects them there per its current auth client).
 *   4. Save context state (cookies + localStorage) to .auth/{persona}.json.
 *
 * Future TOTP variant: replace step 1 with the speakeasy.totp pattern proven
 * in production-uat.spec.ts. Out of scope for #2116-1 (password-only).
 */

import { test as setup, type Page } from '@playwright/test';
import path from 'node:path';

import { applyAuthToLocalStorage, loginViaApi, PERSONAS, type Persona } from './fixtures/auth';

const STAGING_URL =
  process.env.STAGING_URL ?? 'https://etutor.elearning.portfolio2.kimbetien.com';

const AUTH_DIR = path.resolve(__dirname, '.auth');

async function authenticatePersona(page: Page, persona: Persona): Promise<void> {
  // Establish the origin context FIRST so localStorage can be bound to it.
  await page.goto(`${STAGING_URL}/fr/login`, { waitUntil: 'domcontentloaded' });

  // Login via the *page's* request context — Set-Cookie headers populate
  // the same context the browser uses, so the HttpOnly refresh cookie
  // carries through. Using the standalone `request` fixture would create a
  // separate cookie jar and the page would see no auth.
  const login = await loginViaApi(page.request, STAGING_URL, persona);

  // The FE's apiFetch reads access_token from localStorage too — set both.
  await applyAuthToLocalStorage(page, login);

  await page.context().storageState({ path: path.join(AUTH_DIR, `${persona}.json`) });
}

// One setup test per persona — Playwright runs them in parallel within the
// `setup` project, then any project that depends on `setup` runs after all
// of them succeed.
//
// 2116-1 only consumes the `learner` storageState (canary spec). Future PRs
// (2116-2..2116-4) consume the others. Generating all 4 here keeps the
// setup self-contained.

setup('authenticate as learner', async ({ page }) => {
  await authenticatePersona(page, 'learner');
});

setup('authenticate as org-owner', async ({ page }) => {
  await authenticatePersona(page, 'org-owner');
});

setup('authenticate as sub-admin', async ({ page }) => {
  await authenticatePersona(page, 'sub-admin');
});

setup('authenticate as admin', async ({ page }) => {
  await authenticatePersona(page, 'admin');
});

// Smoke check: env vars present for at least the persona we exercise in this
// PR's canary. Throwing here early (rather than mid-test) gives a clearer
// failure message about missing GH Actions secrets.
setup('env vars present', () => {
  const required = ['E2E_LEARNER_PASSWORD'];
  for (const name of required) {
    if (!process.env[name]) {
      throw new Error(
        `${name} is not set. For local runs: export it before running. ` +
          `For CI: add it to GitHub Actions secrets (already done 2026-05-01 — verify with \`gh secret list\`).`,
      );
    }
  }
  // Touch PERSONAS so unused-import warnings don't fire on this single setup.
  void PERSONAS;
});
