import { test, expect } from '@playwright/test';

test.use({ viewport: { width: 360, height: 640 } });

test.describe('Navigation redirects', () => {
  test('/ redirects to /fr/dashboard (not /undefined/dashboard, not /fr/fr/dashboard)', async ({ page }) => {
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

    await page.goto('/');
    await page.waitForURL(/\/fr\/dashboard/, { timeout: 10000 });

    const url = page.url();
    expect(url).toMatch(/\/fr\/dashboard/);
    expect(url).not.toMatch(/\/undefined\//);
    expect(url).not.toMatch(/\/fr\/fr\//);
  });

  test('/fr redirects to /fr/dashboard', async ({ page }) => {
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

    await page.goto('/fr');
    await page.waitForURL(/\/fr\/dashboard/, { timeout: 10000 });

    const url = page.url();
    expect(url).toMatch(/\/fr\/dashboard/);
    expect(url).not.toMatch(/\/undefined\//);
    expect(url).not.toMatch(/\/fr\/fr\//);
  });

  test('login with valid credentials redirects to /fr/dashboard', async ({ page }) => {
    await page.route('**/api/v1/auth/login', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'fake-token',
          refresh_token: 'fake-refresh',
          user: { id: '1', name: 'Dr. Test', email: 'test@example.com' },
        }),
      })
    );

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

    await page.goto('/fr/login');
    await page.locator('#email').fill('test@example.com');
    await page.locator('#totp_code').fill('123456');
    await page.getByRole('button', { name: /Se connecter|Sign in/i }).click();

    await page.waitForURL(/\/fr\/dashboard/, { timeout: 10000 });

    const url = page.url();
    expect(url).toMatch(/\/fr\/dashboard/);
    expect(url).not.toMatch(/\/undefined\//);
    expect(url).not.toMatch(/\/fr\/fr\//);
  });

  test('module unit links resolve without 404', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    await page.goto('/fr/modules/M01');

    const unitLinks = page.locator('a[href*="/modules/M01/"]');
    const count = await unitLinks.count();

    if (count > 0) {
      const href = await unitLinks.first().getAttribute('href');
      expect(href).toBeTruthy();
      expect(href).not.toMatch(/\/undefined\//);
      expect(href).not.toMatch(/\/fr\/fr\//);

      const [response] = await Promise.all([
        page.waitForResponse((r) => r.url().includes(href!) && r.status() !== 500, {
          timeout: 5000,
        }).catch(() => null),
        page.goto(href!),
      ]);

      const url = page.url();
      expect(url).not.toMatch(/\/undefined\//);
      expect(url).not.toMatch(/\/fr\/fr\//);
      await expect(page.locator('body')).not.toContainText('404', { timeout: 5000 });

      void response;
    }
  });

  test('module unit links do not contain /undefined/ in href', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.setItem('access_token', 'fake-token');
      localStorage.setItem('refresh_token', 'fake-refresh');
    });

    await page.goto('/fr/modules/M01');

    const allLinks = await page.locator('a[href]').all();
    for (const link of allLinks) {
      const href = await link.getAttribute('href');
      if (href && href.includes('/modules/')) {
        expect(href).not.toMatch(/\/undefined\//);
        expect(href).not.toMatch(/\/fr\/fr\//);
      }
    }
  });
});
