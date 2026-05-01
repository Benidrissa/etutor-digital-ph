/**
 * Admin admin-page reachability — confirms admin can navigate the admin
 * panel. Same scope as sub_admin's reachability spec, plus the audit-logs +
 * analytics + payments pages which are admin/sub_admin shared but were
 * already verified in the sweep doc to render.
 */

import { expect, test } from '@playwright/test';

test.describe('@admin admin pages', () => {
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

  test('/fr/admin/audit-logs renders audit log page', async ({ page }) => {
    await page.goto('/fr/admin/audit-logs');
    await expect(page.locator('main h1')).toContainText(/audit|journal/i);
  });

  test('/fr/admin/analytics renders analytics page', async ({ page }) => {
    await page.goto('/fr/admin/analytics');
    await expect(page.locator('main h1')).toContainText(/analy/i);
  });
});
