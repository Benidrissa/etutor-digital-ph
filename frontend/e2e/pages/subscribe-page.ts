/**
 * Page object for /[locale]/subscribe — the provider-API payment selector (#2355).
 *
 * Thin wrapper — locators only for the payment-method selector, Pay CTA, the
 * "no methods" empty state, and the inline error. Specs route-mock
 * /api/v1/payments/* so these assertions stay deterministic (see #2419).
 */

import type { Locator, Page } from '@playwright/test';

/** Visible method labels (en locale) keyed by provider id. */
export const METHOD_LABELS = {
  orange_money: 'Orange Money',
  wave: 'Wave',
  paystack: 'Bank card',
} as const;

export type ProviderId = keyof typeof METHOD_LABELS;

export class SubscribePage {
  constructor(public readonly page: Page) {}

  async goto(locale: 'fr' | 'en' = 'en'): Promise<void> {
    await this.page.goto(`/${locale}/subscribe`);
  }

  /** A payment-method option button by provider id (matched on its visible label). */
  methodButton(provider: ProviderId): Locator {
    return this.page.getByRole('button', { name: METHOD_LABELS[provider], exact: true });
  }

  /** The "Pay …" checkout CTA. */
  payButton(): Locator {
    return this.page.getByRole('button', { name: /pay/i });
  }

  /** Empty state shown when no provider is enabled. */
  noMethods(): Locator {
    return this.page.getByText(/no payment method is available/i);
  }

  /** Inline error surfaced when initialize fails (e.g. provider misconfigured). */
  paymentError(): Locator {
    return this.page.getByText(/payment provider error|payment could not be started/i);
  }
}
