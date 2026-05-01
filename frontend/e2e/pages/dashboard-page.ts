/**
 * Page object for /[locale]/dashboard.
 *
 * Thin wrapper — locators only for the elements canary specs need to assert on.
 */

import type { Locator, Page } from '@playwright/test';

export class DashboardPage {
  constructor(public readonly page: Page) {}

  async goto(locale: 'fr' | 'en' = 'fr'): Promise<void> {
    await this.page.goto(`/${locale}/dashboard`);
  }

  heading(): Locator {
    return this.page.getByRole('heading', { name: /^dashboard$/i, level: 1 });
  }

  /** Desktop sidebar — the primary nav role on this page. */
  sidebar(): Locator {
    return this.page.getByRole('navigation', { name: /navigation de bureau|desktop navigation/i });
  }

  /**
   * Returns a locator for a sidebar link by its visible label text.
   *
   * NOTE: cannot use `getByRole('link', { name })` here — the sidebar links
   * have descriptive aria-labels (e.g. "Accéder à votre tableau de bord
   * d'apprentissage" for the Dashboard link) whose role-name doesn't match
   * the visible label "Dashboard". Match by visible text instead.
   */
  sidebarLink(text: string): Locator {
    return this.sidebar().locator('a', { hasText: new RegExp(`^${escapeRegex(text)}$`) });
  }

  /** Returns the visible link texts in order, deduped, empty strings filtered. */
  async sidebarLinkTexts(): Promise<string[]> {
    const links = await this.sidebar().locator('a').all();
    const texts = await Promise.all(links.map((l) => l.textContent()));
    return texts.map((t) => (t ?? '').trim()).filter((t) => t.length > 0);
  }
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
