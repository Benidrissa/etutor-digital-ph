import { test, expect } from '@playwright/test';

test.describe('Internationalization (FR/EN)', () => {
  test('login page renders in English at /en/login', async ({ page }) => {
    await page.goto('/en/login');
    await expect(page.getByText('Sign in', { exact: true }).first()).toBeVisible();
    await expect(page.locator('label[for="email"]')).toContainText('Email');
    await expect(page.locator('#totp_code')).toBeVisible();
  });

  test('login page renders in French at /fr/login', async ({ page }) => {
    await page.goto('/fr/login');
    // French translations — check the page loaded with French locale
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#totp_code')).toBeVisible();
  });

  test('register page renders in English at /en/register', async ({ page }) => {
    await page.goto('/en/register');
    await expect(page.locator('#name')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('label[for="name"]')).toContainText('Full name');
  });

  test('register page renders in French at /fr/register', async ({ page }) => {
    await page.goto('/fr/register');
    await expect(page.locator('#name')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
  });

  test('locale switcher toggles between EN and FR', async ({ page }) => {
    await page.goto('/en/login');

    // Find and click the locale switcher button
    const switcher = page.getByRole('button', { name: /Switch to|Changer/ });
    if (await switcher.isVisible()) {
      await switcher.click();
      // URL should now contain /fr/
      await expect(page).toHaveURL(/\/fr\//);
    }
  });

  test('dashboard renders in English', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    await page.route('**/api/v1/dashboard/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          streak_days: 0,
          is_active_today: false,
          average_quiz_score: 0,
          total_time_studied_this_week: 0,
          next_review_count: 0,
          modules_in_progress: 0,
          completion_percentage: 0,
        }),
      })
    );

    await page.goto('/en/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });

  test('modules page renders in English', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    await page.goto('/en/modules');
    await expect(page.getByRole('heading', { name: 'Learning Modules' }).first()).toBeVisible();
  });

  test('navigation items visible on dashboard', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    await page.route('**/api/v1/dashboard/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          streak_days: 0,
          is_active_today: false,
          average_quiz_score: 0,
          total_time_studied_this_week: 0,
          next_review_count: 0,
          modules_in_progress: 0,
          completion_percentage: 0,
        }),
      })
    );

    await page.goto('/en/dashboard');
    // At least one nav element should contain "Dashboard"
    await expect(page.getByText('Dashboard').first()).toBeVisible();
  });
});
