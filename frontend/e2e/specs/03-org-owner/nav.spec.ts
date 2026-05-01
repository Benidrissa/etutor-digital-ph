/**
 * Org-owner sidebar nav — verifies role-scoped UI gating.
 *
 * The org-owner is a `role=user` who owns at least one organization. Per the
 * role-model pivot (#2134, project_role_model_pivot.md), this is the new
 * canonical "expert" — their elevated capabilities come from
 * OrgMemberRole.owner, not from a platform UserRole.
 *
 * Expected sidebar shape:
 *   - all 9 learner links visible (Dashboard / Formations / Modules / etc.)
 *   - "Organisations" visible (they own one)
 *   - "Administration" hidden (platform-admin gating, not theirs)
 *
 * Server-side RBAC for admin endpoints was independently verified during the
 * 2026-04-30 sweep — this spec catches frontend nav-gating regressions
 * specifically.
 */

import { expect, test } from '@playwright/test';

import { DashboardPage } from '../../pages/dashboard-page';

test.describe('@org-owner nav', () => {
  test.fixme(
    'sidebar shows Organisations link (user has org membership) — BLOCKED on #2137',
    async ({ page }) => {
      const dashboard = new DashboardPage(page);
      await dashboard.goto('fr');

      // Today this fails because frontend/components/layout/sidebar.tsx:163-172
      // gates Organisations on `userRole === "admin" || userRole === "sub_admin"`
      // — explicitly NOT on expert or on "user with org membership". So a
      // role=user org-owner (the new canonical "expert" per role-model pivot
      // #2134) does NOT see the link.
      //
      // The frontend phase of the migration (#2137) replaces that gating with
      // a "user has at least one OrgMembership" check. When that lands,
      // remove the .fixme — this test should pass.
      await expect(
        dashboard.sidebarLink('Organisations'),
        'expected Organisations link visible for an org-member user (post-migration target state)',
      ).toBeVisible();
    },
  );

  test('sidebar hides Administration link (org-owner is not platform admin)', async ({ page }) => {
    const dashboard = new DashboardPage(page);
    await dashboard.goto('fr');

    await expect(
      dashboard.sidebarLink('Administration'),
      'expected Administration link hidden for an org-owner who is not role=admin',
    ).toHaveCount(0);
  });
});
