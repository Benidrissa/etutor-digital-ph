import { test, expect } from '@playwright/test';

test.describe('Modules Page', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });
  });

  test('renders modules page with Learning Modules heading', async ({ page }) => {
    await page.goto('/en/modules');
    // The main content area has the heading
    await expect(page.getByRole('heading', { name: 'Learning Modules' }).first()).toBeVisible();
    await expect(
      page.getByText('Track your progress through the public health curriculum').first()
    ).toBeVisible();
  });

  test('displays curriculum levels', async ({ page }) => {
    await page.goto('/en/modules');
    // Check for level headings in the main content
    await expect(page.getByText('Beginner').first()).toBeVisible();
    await expect(page.getByText('Intermediate').first()).toBeVisible();
  });

  test('shows module cards with titles', async ({ page }) => {
    await page.goto('/en/modules');
    // First module should always be visible
    await expect(page.getByText('Foundations of Public Health').first()).toBeVisible();
  });

  test('locked modules have disabled buttons', async ({ page }) => {
    await page.goto('/en/modules');
    // Look for disabled "Start" buttons (locked modules)
    const disabledButtons = page.locator('button:disabled', { hasText: 'Start' });
    // There should be some locked modules
    const count = await disabledButtons.count();
    expect(count).toBeGreaterThan(0);
  });

  test('shows overall progress summary section', async ({ page }) => {
    await page.goto('/en/modules');
    // Scroll to the bottom to find the progress summary
    const progressHeading = page.getByRole('heading', { name: 'Overall Progress' });
    await progressHeading.scrollIntoViewIfNeeded();
    await expect(progressHeading).toBeVisible();
  });

  test('clicking an unlocked module navigates to module overview', async ({ page }) => {
    await page.goto('/en/modules');
    // Click the first module card's action button
    const startButtons = page.locator('button:not(:disabled)', { hasText: /Start|Continue/ });
    if ((await startButtons.count()) > 0) {
      await startButtons.first().click();
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

  test('displays learning objectives section', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Learning Objectives')).toBeVisible();
  });

  test('displays units section heading', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await expect(page.getByText('Units', { exact: true }).first()).toBeVisible();
  });

  test('shows progress percentage', async ({ page }) => {
    await page.goto('/en/modules/M01');
    // Progress section shows a percentage
    await expect(page.getByText(/\d+%/).first()).toBeVisible();
  });

  test('back button navigates to modules list', async ({ page }) => {
    await page.goto('/en/modules/M01');
    await page.getByText('Back to Modules').click();
    await expect(page).toHaveURL(/\/modules$/);
  });
});
