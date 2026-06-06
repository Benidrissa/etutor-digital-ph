/**
 * Payment-method selector on /subscribe — all three modes (#2419, follow-up to #2355).
 *
 * Route-mocked: GET /api/v1/payments/providers and /subscriptions/me are
 * intercepted so the test is deterministic and never mutates shared staging
 * platform settings. Service workers are blocked so the PWA's stale-while-
 * revalidate api-responses cache can't shadow the mocked responses.
 */

import { expect, test } from '@playwright/test';
import { SubscribePage } from '../../pages/subscribe-page';

const PROVIDERS_URL = '**/api/v1/payments/providers';
const INITIALIZE_URL = '**/api/v1/payments/initialize';
const SUBSCRIPTION_ME = '**/api/v1/subscriptions/me';

const ALL_THREE = ['orange_money', 'wave', 'paystack'];

// Free-tier subscription so isActive=false and the selector renders, regardless
// of the e2e-learner fixture's real subscription state.
const FREE_TIER = {
  has_subscription: false,
  free_tier: { daily_messages: 5, first_lesson_free: true },
};

async function mockProviders(page: import('@playwright/test').Page, providers: string[]) {
  await page.route(PROVIDERS_URL, (route) => route.fulfill({ json: { providers } }));
}

test.describe('@learner subscribe — payment methods', () => {
  // Block the service worker so page.route() always intercepts the API calls.
  test.use({ serviceWorkers: 'block' });

  test.beforeEach(async ({ page }) => {
    await page.route(SUBSCRIPTION_ME, (route) => route.fulfill({ json: FREE_TIER }));
  });

  test('renders Orange Money, Wave and Bank card when all are enabled', async ({ page }) => {
    await mockProviders(page, ALL_THREE);
    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');

    await expect(subscribe.methodButton('orange_money')).toBeVisible();
    await expect(subscribe.methodButton('wave')).toBeVisible();
    await expect(subscribe.methodButton('paystack')).toBeVisible();
    await expect(subscribe.payButton()).toBeVisible();

    // First provider is selected by default.
    await expect(subscribe.methodButton('orange_money')).toHaveAttribute('aria-pressed', 'true');
  });

  test('selecting a method moves the aria-pressed state', async ({ page }) => {
    await mockProviders(page, ALL_THREE);
    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');

    await subscribe.methodButton('wave').click();
    await expect(subscribe.methodButton('wave')).toHaveAttribute('aria-pressed', 'true');
    await expect(subscribe.methodButton('orange_money')).toHaveAttribute('aria-pressed', 'false');
    await expect(subscribe.methodButton('paystack')).toHaveAttribute('aria-pressed', 'false');
  });

  test('shows only the enabled providers (Paystack only → Bank card only)', async ({ page }) => {
    await mockProviders(page, ['paystack']);
    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');

    await expect(subscribe.methodButton('paystack')).toBeVisible();
    await expect(subscribe.methodButton('orange_money')).toHaveCount(0);
    await expect(subscribe.methodButton('wave')).toHaveCount(0);
  });

  test('shows the empty state when no provider is enabled', async ({ page }) => {
    await mockProviders(page, []);
    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');

    await expect(subscribe.noMethods()).toBeVisible();
    await expect(subscribe.payButton()).toHaveCount(0);
  });

  test('Pay posts the selected provider to initialize and follows checkout_url', async ({
    page,
  }) => {
    await mockProviders(page, ALL_THREE);

    // Stub the provider's hosted checkout so window.location redirect resolves.
    await page.route('https://provider.test/**', (route) =>
      route.fulfill({ contentType: 'text/html', body: 'ok' }),
    );
    await page.route(INITIALIZE_URL, (route) => {
      const body = route.request().postDataJSON();
      return route.fulfill({
        json: {
          checkout_url: 'https://provider.test/checkout/abc',
          reference: 'sira_test',
          provider: body.provider,
        },
      });
    });

    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');
    await subscribe.methodButton('wave').click();

    const initReq = page.waitForRequest(INITIALIZE_URL);
    await subscribe.payButton().click();
    const body = (await initReq).postDataJSON();

    expect(body.provider).toBe('wave');
    expect(body.payment_type).toBe('access');
  });

  test('surfaces an inline error when initialize fails', async ({ page }) => {
    await mockProviders(page, ['paystack']);
    await page.route(INITIALIZE_URL, (route) =>
      route.fulfill({ status: 502, json: { detail: 'Payment provider error' } }),
    );

    const subscribe = new SubscribePage(page);
    await subscribe.goto('en');
    await subscribe.payButton().click();

    await expect(subscribe.paymentError()).toBeVisible();
  });
});
