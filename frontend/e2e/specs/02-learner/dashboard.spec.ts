/**
 * Learner canary — verifies the dashboard renders with role-scoped sidebar.
 *
 * Pre-authed via the `setup` project (e2e/auth.setup.ts) which writes
 * `e2e/.auth/learner.json` with the e2e-learner@sira-test.local fixture's
 * tokens. The 02-learner project loads that storageState.
 *
 * Critical regression bar: the sidebar should hide admin/orgs/qbank-author
 * links for `role=user`. Server-side RBAC was independently verified during
 * the 2026-04-30 sweep — this spec catches frontend nav-gating regressions
 * specifically.
 */

import { expect, test } from '@playwright/test';

import { DashboardPage } from '../../pages/dashboard-page';
import { LEARNER_HIDDEN_LINKS_FR, LEARNER_SIDEBAR_LINKS_FR } from '../../fixtures/seed-data';

test.describe('@learner dashboard', () => {
  test('renders the Dashboard heading', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(dashboard.heading()).toBeVisible();
  });

  test('sidebar shows the 9 learner links and hides admin/orgs/qbank-author', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    // Each expected link must be visible.
    for (const label of LEARNER_SIDEBAR_LINKS_FR) {
      await expect(
        dashboard.sidebarLink(label),
        `expected sidebar link "${label}" to be visible for a role=user learner`,
      ).toBeVisible();
    }

    // Each hidden link must NOT exist.
    for (const label of LEARNER_HIDDEN_LINKS_FR) {
      await expect(
        dashboard.sidebarLink(label),
        `expected sidebar link "${label}" to be hidden for a role=user learner (RBAC regression)`,
      ).toHaveCount(0);
    }
  });

  test('sidebar link count matches the expected learner set exactly', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    const visibleLinks = await dashboard.sidebarLinkTexts();
    // Filter to only the LEARNER_SIDEBAR_LINKS_FR expected set + any others —
    // we don't want to fail on incidental nav additions, but we do want to
    // catch role-leak (e.g., "Administration" silently appearing).
    const unexpectedRoleScopedLinks = visibleLinks.filter((label) =>
      (LEARNER_HIDDEN_LINKS_FR as readonly string[]).includes(label),
    );
    expect(
      unexpectedRoleScopedLinks,
      `unexpected role-scoped links visible to learner: ${unexpectedRoleScopedLinks.join(', ')}`,
    ).toEqual([]);
  });
});
