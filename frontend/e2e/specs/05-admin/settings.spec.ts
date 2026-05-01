/**
 * Admin settings access — the distinguishing canary for admin vs sub_admin.
 *
 * Sub_admin gets 403 on /api/v1/admin/settings (verified in 04-sub-admin/
 * settings-403.spec.ts); admin should get 200 and the page should render
 * the categories list.
 *
 * Per `backend/app/api/v1/admin_settings.py:57`, /admin/settings is gated on
 * UserRole.admin only.
 */

import { expect, test } from '@playwright/test';

const STAGING_API =
  process.env.STAGING_API ||
  (process.env.STAGING_URL || 'https://etutor.elearning.portfolio2.kimbetien.com').replace(
    /^https:\/\/etutor\./,
    'https://api.',
  );

test.describe('@admin settings access', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/fr/dashboard');
  });

  test('GET /api/v1/admin/settings returns 200 for admin', async ({ page }) => {
    const accessToken = await page.evaluate(() => localStorage.getItem('access_token'));
    const res = await page.request.get(`${STAGING_API}/api/v1/admin/settings`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(res.status()).toBe(200);

    // Response is a list of category objects; quick shape check.
    const body = await res.json();
    expect(Array.isArray(body), 'expected /admin/settings to return an array of categories').toBe(
      true,
    );
    expect(body.length).toBeGreaterThan(0);
  });

  test('/fr/admin/settings page renders the categories list', async ({ page }) => {
    await page.goto('/fr/admin/settings');

    await expect(page.locator('main h1')).toContainText(/paramètres|settings/i);

    // Verified during 2026-04-30 sweep — these category labels appear on
    // /fr/admin/settings (some are correctly localized, some leak raw
    // English — see #2128 for the i18n audit follow-up). Just check that
    // *some* categories render.
    await expect(
      page.getByText(/AI.*Content Generation|Auth.*Security|Quiz.*Assessment/i).first(),
    ).toBeVisible();
  });
});
