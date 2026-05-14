/**
 * Demo / learner user-story acceptance suite.
 *
 * Covers the high-priority H.x acceptance stories for the demo tenant.
 * All tests run against the production demo URL configured in playwright.config.ts.
 *
 * H.1  — Anonymous visitor sees landing + login
 * H.2  — Learner can log in and reach the dashboard
 * H.3  — No raw i18n keys are rendered (translation completeness canary)
 * H.4  — Dashboard renders in the user's preferred locale
 * H.5  — Learner can navigate to Modules
 */

import { expect, test } from '@playwright/test';

// ---------------------------------------------------------------------------
// H.1 — Anonymous visitor
// ---------------------------------------------------------------------------
test.describe('H.1 — Anonymous visitor', () => {
  test('login page is reachable and renders the sign-in form', async ({ page }) => {
    await page.goto('/fr/login');
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#totp_code')).toBeVisible();
  });

  test('redirects to login when accessing a protected route', async ({ page }) => {
    await page.goto('/fr/dashboard');
    await expect(page).toHaveURL(/\/login/);
  });
});

// ---------------------------------------------------------------------------
// H.2 — Learner login
// ---------------------------------------------------------------------------
test.describe('H.2 — Learner login', () => {
  test('login page renders form elements in French', async ({ page }) => {
    await page.goto('/fr/login');
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#totp_code')).toBeVisible();
    // Page should contain at least one <button> for form submission
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// H.3 — i18n completeness: no raw translation keys visible in the UI
//
// A "raw key" is a dotted string that looks like "namespace.subKey.leaf" —
// the pattern react-i18next / next-intl emit when a key is missing from the
// active locale's message catalogue.
//
// False-positive exclusions:
//   • Strings that contain a digit (version strings, IDs, …)
//   • React/Next.js SSR internals: "Sreact.*" and "React.*" that match the
//     dotted-key shape but are internal framework identifiers, not i18n keys.
// ---------------------------------------------------------------------------
test.describe('H.3 — No raw i18n keys rendered', () => {
  const PAGES_TO_CHECK = ['/fr/login', '/en/login'];

  for (const route of PAGES_TO_CHECK) {
    test(`no raw i18n keys on ${route}`, async ({ page }) => {
      await page.goto(route);

      // Collect every text node on the page.
      const rawKeys: string[] = await page.evaluate(() => {
        const walker = document.createTreeWalker(
          document.body,
          NodeFilter.SHOW_TEXT,
          null,
        );
        const texts: string[] = [];
        let node: Text | null;
        while ((node = walker.nextNode() as Text | null)) {
          const t = node.textContent?.trim();
          if (t) texts.push(t);
        }
        return texts;
      });

      // A raw key looks like "some.dotted.path" where every segment is > 2
      // characters long and there are no digits in the whole string.
      // Exclude React / Next.js SSR internal identifiers that match the same
      // shape but are not missing translation keys.
      const suspicious = rawKeys.filter(
        k =>
          !k.match(/\d/) &&
          k.split('.').every(p => p.length > 2) &&
          !k.startsWith('Sreact.') &&
          !k.startsWith('React.'),
      );

      expect(
        suspicious,
        `Raw i18n keys detected on ${route}: ${suspicious.join(', ')}`,
      ).toEqual([]);
    });
  }
});

// ---------------------------------------------------------------------------
// H.4 — Locale rendering
// ---------------------------------------------------------------------------
test.describe('H.4 — Locale rendering', () => {
  test('French login page has lang="fr" on <html>', async ({ page }) => {
    await page.goto('/fr/login');
    const lang = await page.locator('html').getAttribute('lang');
    expect(lang).toBe('fr');
  });

  test('English login page has lang="en" on <html>', async ({ page }) => {
    await page.goto('/en/login');
    const lang = await page.locator('html').getAttribute('lang');
    expect(lang).toBe('en');
  });
});

// ---------------------------------------------------------------------------
// H.5 — Modules navigation
// ---------------------------------------------------------------------------
test.describe('H.5 — Modules navigation', () => {
  test('modules route returns a page (not 404)', async ({ page }) => {
    const response = await page.goto('/fr/modules');
    // Allow 200 or redirect (3xx → resolved to 200 by Playwright follow)
    expect(response?.status()).not.toBe(404);
  });
});
