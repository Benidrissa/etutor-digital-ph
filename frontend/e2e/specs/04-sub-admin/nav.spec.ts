/**
 * Sub_admin sidebar nav — verifies role-scoped UI.
 *
 * Sub_admin sees the same admin nav links as admin (Administration,
 * Organisations, QBank-author) but the API gates `/admin/settings/*`
 * to UserRole.admin only — that's the canary in settings-403.spec.ts.
 */

import { expect, test } from '@playwright/test';

import { DashboardPage } from '../../pages/dashboard-page';

test.describe('@sub-admin nav', () => {
  test('sidebar shows Administration link', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(dashboard.sidebarLink('Administration')).toBeVisible();
  });

  test('sidebar shows Organisations link (admin/sub_admin gated)', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(dashboard.sidebarLink('Organisations')).toBeVisible();
  });
});
