/**
 * Org-owner dashboard — /[locale]/org/{slug} renders the org's dashboard
 * with the org name as h1 and stat tiles.
 *
 * Fixture: e2e-test-org (slug from #2109 seed, see SEED_ORG in fixtures/seed-data.ts).
 */

import { expect, test } from '@playwright/test';

import { OrgPage } from '../../pages/org-page';
import { SEED_ORG } from '../../fixtures/seed-data';

test.describe('@org-owner dashboard', () => {
  test('renders the org name as h1', async ({ page }) => {
    const org = new OrgPage(page);
    await org.gotoDashboard(SEED_ORG.slug, 'fr');

    await expect(org.heading()).toHaveText(SEED_ORG.name, { ignoreCase: true });
  });

  test('shows the standard org stat tiles (codes, apprenants, complétion, crédits)', async ({
    page,
  }) => {
    const org = new OrgPage(page);
    await org.gotoDashboard(SEED_ORG.slug, 'fr');

    // Stat tile labels confirmed during the 2026-04-30 sweep.
    for (const label of ['Total codes', 'Apprenants total', 'Complétion', 'Crédits']) {
      await expect(
        page.getByText(label, { exact: false }).first(),
        `expected stat tile "${label}" visible on org dashboard`,
      ).toBeVisible();
    }
  });

  test('navigates from /fr/organizations index to the org dashboard', async ({ page }) => {
    await page.goto('/fr/organizations');

    // The org-owner sees their org listed as a card with "Propriétaire" badge.
    const orgCard = page.locator('main a').filter({ hasText: SEED_ORG.name });
    await expect(orgCard).toBeVisible();

    // Click through to /fr/org/{slug}.
    await orgCard.click();
    await expect(page).toHaveURL(new RegExp(`/fr/org/${SEED_ORG.slug}/?$`));
  });
});
