/**
 * Page object for /[locale]/org/{slug} and its sub-routes.
 *
 * Thin wrapper — locators only.
 *
 * Routes covered (verified during 2026-04-30 sweep — all 200):
 *   /fr/org/{slug}                org dashboard (stats, quick links)
 *   /fr/org/{slug}/courses        course list
 *   /fr/org/{slug}/curricula      curriculum list
 *   /fr/org/{slug}/qbank          question banks
 *   /fr/org/{slug}/codes          activation codes
 *   /fr/org/{slug}/reports        learner reports
 *   /fr/org/{slug}/members        org members
 */

import type { Locator, Page } from '@playwright/test';

export class OrgPage {
  constructor(public readonly page: Page) {}

  async gotoDashboard(slug: string, locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/org/${slug}`);
  }

  async gotoCourses(slug: string, locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/org/${slug}/courses`);
  }

  async gotoCodes(slug: string, locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/org/${slug}/codes`);
  }

  async gotoMembers(slug: string, locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/org/${slug}/members`);
  }

  /** Org-name heading on the dashboard view. */
  heading(): Locator {
    return this.page.locator('main h1');
  }

  /** Stat tile by label (e.g. "Total codes", "Apprenants total"). */
  statTile(label: string): Locator {
    return this.page.locator('main', { hasText: label });
  }

  /** Course card by slug (the slug is rendered as a link href). */
  courseLink(slug: string): Locator {
    return this.page.locator(`main a[href*="/courses/"][href$="${slug}"], main a[href*="/${slug}"]`);
  }

  /**
   * Activation code row by code value.
   * Matches any element whose text contains the code (the table cell or chip).
   */
  activationCodeRow(code: string): Locator {
    return this.page.locator('main').getByText(code, { exact: true });
  }
}
