/**
 * Production read-only smoke (#2116-5/5, completes #2116; runs hourly via
 * cron in #2118).
 *
 * Targets PROD_URL (default https://sira-donnia.org) — separate from the
 * persona projects which target staging. Anonymous-only — no fixture
 * accounts on prod, no CRUD, no AI tokens. Each test is a single GET
 * assertion; the suite should complete in well under 60s.
 *
 * What this catches:
 *   - Public-facing pages crash or return 5xx
 *   - PWA service worker disappears (#2113 regression)
 *   - Curricula index disappears (#2111 regression)
 *   - Public-settings endpoint becomes unreachable
 *   - Authenticated endpoints stop returning 401 for anonymous (auth-bypass
 *     regression — would be a serious security bug)
 *
 * What this does NOT catch:
 *   - Auth flows (covered by persona suite on staging)
 *   - Role-scoped behavior (covered by persona suite on staging)
 *   - Anything that requires login
 */

import { expect, test } from '@playwright/test';

// Prod FE lives at app.sira-donnia.org (the bare sira-donnia.org domain is a
// parked redirect — staying away from it). API lives at api.sira-donnia.org.
const PROD_URL = process.env.PROD_URL || 'https://app.sira-donnia.org';
const PROD_API = process.env.PROD_API || 'https://api.sira-donnia.org';

test.describe('@smoke production read-only', () => {
  test('backend /health returns healthy', async ({ request }) => {
    const res = await request.get(`${PROD_API}/health`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.status).toBe('healthy');
  });

  test('public settings endpoint returns 200', async ({ request }) => {
    const res = await request.get(`${PROD_API}/api/v1/settings/public`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body).toHaveProperty('settings');
    expect(body).toHaveProperty('branding');
  });

  test.fixme(
    'PWA service worker /sw.js is reachable — pending #2113 deploy to prod',
    async ({ request }) => {
      // F-005 sentinel. #2113 + #2146 added the SW build; both are merged on
      // main but verified 404 on app.sira-donnia.org/sw.js as of 2026-05-01.
      // Remove .fixme once a prod deploy ships the fix — then this smoke
      // catches future regressions.
      const res = await request.get(`${PROD_URL}/sw.js`);
      expect(res.status()).toBe(200);
      const body = await res.text();
      expect(body.length).toBeGreaterThan(0);
    },
  );

  test('anonymous can browse courses catalog', async ({ page }) => {
    await page.goto(`${PROD_URL}/fr/courses`);
    await expect(page.locator('main h1')).toContainText(/catalogue|formation/i);
  });

  test('anonymous can view curricula index', async ({ page }) => {
    // F-003 sentinel — /fr/curricula was 404 on staging during the 2026-04-30
    // sweep (#2111). Catches a future regression of the same shape.
    await page.goto(`${PROD_URL}/fr/curricula`);
    await expect(page).not.toHaveTitle(/404/i);
  });

  test('anonymous about page renders', async ({ page }) => {
    await page.goto(`${PROD_URL}/fr/about`);
    await expect(page.locator('h1')).toBeVisible();
  });

  test('anonymous login page renders form', async ({ page }) => {
    await page.goto(`${PROD_URL}/fr/login`);
    await expect(page.locator('input[name="identifier"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toBeVisible();
  });

  test('English locale renders /en/about', async ({ page }) => {
    await page.goto(`${PROD_URL}/en/about`);
    await expect(page.locator('h1')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('en');
  });

  test('protected admin endpoint rejects anonymous (auth-bypass sentinel)', async ({ request }) => {
    // Critical security check — if this ever returns 200, it means an
    // auth-bypass regression shipped to prod.
    const res = await request.get(`${PROD_API}/api/v1/admin/users?offset=0&limit=1`);
    expect(res.status()).toBe(401);
  });

  test('protected user endpoint rejects anonymous', async ({ request }) => {
    const res = await request.get(`${PROD_API}/api/v1/users/me`);
    expect(res.status()).toBe(401);
  });
});
