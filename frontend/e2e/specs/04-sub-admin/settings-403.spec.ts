/**
 * Sub_admin settings restriction — the distinguishing canary for this role.
 *
 * `backend/app/api/v1/admin_settings.py:57,71,99,125` gates ALL settings
 * endpoints on `UserRole.admin` only — sub_admin is NOT included. This spec
 * confirms the restriction holds at the API layer.
 *
 * Memory `project_saas_reseller` notes: "Phase 0 done (BACKEND_URL,
 * sub_admin)" and #1365 added sub_admin specifically to restrict AI/prompt
 * settings access. The current implementation is broader — sub_admin can't
 * touch ANY settings — but that's the production state we want pinned.
 */

import { expect, test } from '@playwright/test';

const STAGING_API =
  process.env.STAGING_API ||
  (process.env.STAGING_URL || 'https://etutor.elearning.portfolio2.kimbetien.com').replace(
    /^https:\/\/etutor\./,
    'https://api.',
  );

test.describe('@sub-admin settings restriction', () => {
  // Navigate to origin first so localStorage is accessible (otherwise
  // page.evaluate fires on about:blank and SecurityError-rejects the
  // localStorage read).
  test.beforeEach(async ({ page }) => {
    await page.goto('/fr/dashboard');
  });

  test('GET /api/v1/admin/settings returns 403 for sub_admin (admin-only endpoint)', async ({
    page,
  }) => {
    const accessToken = await page.evaluate(() => localStorage.getItem('access_token'));
    expect(accessToken, 'sub_admin storageState should include access_token').toBeTruthy();

    const res = await page.request.get(`${STAGING_API}/api/v1/admin/settings`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(res.status()).toBe(403);

    const body = await res.json();
    expect(body.detail).toMatch(/insufficient permissions|forbidden/i);
  });

  test('GET /api/v1/admin/users succeeds for sub_admin (allowed admin endpoint)', async ({
    page,
  }) => {
    // Negative-control: confirm the 403 above isn't a generic "all admin
    // routes are blocked" — sub_admin should reach /admin/users fine.
    const accessToken = await page.evaluate(() => localStorage.getItem('access_token'));
    const res = await page.request.get(`${STAGING_API}/api/v1/admin/users?offset=0&limit=1`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    expect(res.status()).toBe(200);
  });
});
