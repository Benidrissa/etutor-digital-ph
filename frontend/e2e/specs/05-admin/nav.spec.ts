/**
 * Admin sidebar nav — verifies the highest-privilege persona's nav.
 *
 * Admin sees the same admin nav links as sub_admin (Administration,
 * Organisations, QBank-author). The distinguishing capability — settings
 * page access — is covered by settings.spec.ts via direct API + UI checks.
 */

import { expect, test } from '@playwright/test';

import { DashboardPage } from '../../pages/dashboard-page';

test.describe('@admin nav', () => {
  test('sidebar shows Administration link', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(dashboard.sidebarLink('Administration')).toBeVisible();
  });

  test('sidebar shows Organisations link', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(dashboard.sidebarLink('Organisations')).toBeVisible();
  });
});
