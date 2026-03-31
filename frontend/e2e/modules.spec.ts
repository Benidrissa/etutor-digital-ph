import { test, expect } from '@playwright/test';

test.describe('Modules Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });
  });

  test('renders modules page with title', async ({ page }) => {
    await page.goto('/en/modules');
    await expect(page.getByText('Learning Modules')).toBeVisible();
    await expect(
      page.getByText('Track your progress through the public health curriculum')
    ).toBeVisible();
  });

  test('displays all 4 curriculum levels', async ({ page }) => {
    await page.goto('/en/modules');
    await expect(page.getByText(/Level 1/)).toBeVisible();
    await expect(page.getByText(/Level 2/)).toBeVisible();
    await expect(page.getByText(/Level 3/)).toBeVisible();
    await expect(page.getByText(/Level 4/)).toBeVisible();
  });

  test('shows module cards with numbers and titles', async ({ page }) => {
    await page.goto('/en/modules');
    // Module 1 should be visible (first module, always unlocked)
    await expect(page.getByText('1').first()).toBeVisible();
  });

  test('locked modules have disabled buttons', async ({ page }) => {
    await page.goto('/en/modules');
    // Look for disabled "Start" buttons (locked modules)
    const disabledButtons = page.locator('button:disabled', { hasText: 'Start' });
    // There should be some locked modules
    const count = await disabledButtons.count();
    expect(count).toBeGreaterThan(0);
  });

  test('shows overall progress summary', async ({ page }) => {
    await page.goto('/en/modules');
    await expect(page.getByText('Overall Progress')).toBeVisible();
    await expect(page.getByText('320 total hours')).toBeVisible();
    await expect(page.getByText('Estimated 6-12 months to complete')).toBeVisible();
  });

  test('clicking an unlocked module navigates to module overview', async ({ page }) => {
    await page.goto('/en/modules');
    // Click the first module card's action button (should be "Start" for M01)
    const startButtons = page.locator('button:not(:disabled)', { hasText: /Start|Continue/ });
    if ((await startButtons.count()) > 0) {
      await startButtons.first().click();
      // Should navigate to module overview page
      await expect(page).toHaveURL(/\/modules\/M0/);
    }
  });
});

test.describe('Module Overview Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });
  });

  test('renders module overview with back button', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Back to Modules')).toBeVisible();
  });

  test('displays learning objectives', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Learning Objectives')).toBeVisible();
  });

  test('displays units section', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Units')).toBeVisible();
  });

  test('shows progress section', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Progress')).toBeVisible();
  });

  test('back button navigates to modules list', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await page.getByText('Back to Modules').click();
    await expect(page).toHaveURL(/\/modules$/);
  });
});
