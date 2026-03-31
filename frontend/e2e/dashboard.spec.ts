import { test, expect } from '@playwright/test';

// Mock dashboard stats response
const MOCK_STATS = {
  streak_days: 5,
  is_active_today: true,
  average_quiz_score: 78.5,
  total_time_studied_this_week: 45,
  next_review_count: 12,
  modules_in_progress: 2,
  completion_percentage: 35,
};

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    // Mock auth — set a fake token so the page doesn't redirect to login
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    // Mock the dashboard stats API
    await page.route('**/api/v1/dashboard/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_STATS),
      })
    );
  });

  test('renders dashboard page with title and subtitle', async ({ page }) => {
    await page.goto('/en/dashboard');
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByText('Your public health learning platform')).toBeVisible();
  });

  test('displays all 6 stat cards with correct data', async ({ page }) => {
    await page.goto('/en/dashboard');

    // Streak
    await expect(page.getByText('Active today!')).toBeVisible({ timeout: 10000 });

    // Average quiz score
    await expect(page.getByText('79%')).toBeVisible(); // Math.round(78.5)

    // Weekly study time
    await expect(page.getByText('45')).toBeVisible();
    await expect(page.getByText('minutes')).toBeVisible();

    // Due reviews
    await expect(page.getByText('12')).toBeVisible();

    // Modules in progress
    await expect(page.getByText('2')).toBeVisible();

    // Overall progress
    await expect(page.getByText('35%')).toBeVisible();
  });

  test('shows loading skeletons before data loads', async ({ page }) => {
    // Delay the API response
    await page.route('**/api/v1/dashboard/stats', async (route) => {
      await new Promise((r) => setTimeout(r, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_STATS),
      });
    });

    await page.goto('/en/dashboard');
    // Skeleton cards should appear (they have animate-pulse class)
    const skeletons = page.locator('.animate-pulse');
    await expect(skeletons.first()).toBeVisible();
  });

  test('shows error state when API fails', async ({ page }) => {
    await page.route('**/api/v1/dashboard/stats', (route) =>
      route.fulfill({ status: 500, body: 'Internal Server Error' })
    );

    await page.goto('/en/dashboard');
    await expect(page.getByText('An error occurred')).toBeVisible({ timeout: 10000 });
  });
});
