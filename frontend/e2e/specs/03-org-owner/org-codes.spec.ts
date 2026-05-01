/**
 * Org-owner activation codes view — /[locale]/org/{slug}/codes lists
 * activation codes scoped to the org. Seeded code: E2E-FIXTURE-CODE
 * (see SEED_ACTIVATION_CODE in fixtures/seed-data.ts).
 */

import { expect, test } from '@playwright/test';

import { OrgPage } from '../../pages/org-page';
import { SEED_ACTIVATION_CODE, SEED_ORG } from '../../fixtures/seed-data';

test.describe('@org-owner activation codes', () => {
  test('lists the seeded fixture activation code', async ({ page }) => {
    const org = new OrgPage(page);
    await org.gotoCodes(SEED_ORG.slug, 'fr');

    await expect(
      page.getByText(SEED_ACTIVATION_CODE, { exact: false }).first(),
      `expected activation code "${SEED_ACTIVATION_CODE}" visible in org's codes list`,
    ).toBeVisible();
  });
});
