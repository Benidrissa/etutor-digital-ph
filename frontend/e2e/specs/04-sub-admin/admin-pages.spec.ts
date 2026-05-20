/**
 * Sub_admin admin-page reachability — confirms sub_admin can navigate to and
 * load the admin pages they're authorized for.
 *
 * Per `backend/app/api/v1/admin_*.py`, sub_admin is included in
 * `require_role(UserRole.admin, UserRole.sub_admin)` for users / courses /
 * curricula / taxonomy / groups / payments / audit-logs / analytics / qbank.
 * Only `/admin/settings/*` is admin-only — covered by settings-403.spec.ts.
 */

import { expect, test } from '@playwright/test';

test.describe('@sub-admin admin pages', () => {
  test('/fr/admin/users renders user-management page', async ({ page }) => {
    await page.goto('/fr/admin/users');
    await expect(page.locator('main h1')).toContainText(/utilisateurs|user/i);
  });

  test('/fr/admin/courses renders course-management page', async ({ page }) => {
    await page.goto('/fr/admin/courses');
    await expect(page.locator('main h1')).toContainText(/formations|courses/i);
  });

  test('/fr/admin/curricula renders curriculum-management page', async ({ page }) => {
    await page.goto('/fr/admin/curricula');
    await expect(page.locator('main h1')).toContainText(/curricula/i);
  });

  test('/fr/admin/taxonomy renders taxonomy page', async ({ page }) => {
    await page.goto('/fr/admin/taxonomy');
    await expect(page.locator('main h1')).toContainText(/taxonom/i);
  });
});
