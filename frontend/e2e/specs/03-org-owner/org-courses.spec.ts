/**
 * Org-owner courses view — /[locale]/org/{slug}/courses lists the org's
 * courses (e2e-published-course + e2e-draft-course from the #2109 seed).
 */

import { expect, test } from '@playwright/test';

import { OrgPage } from '../../pages/org-page';
import { SEED_COURSES, SEED_ORG } from '../../fixtures/seed-data';

test.describe('@org-owner courses', () => {
  test('lists both seeded courses (published + draft)', async ({ page }) => {
    const org = new OrgPage(page);
    await org.gotoCourses(SEED_ORG.slug, 'fr');

    // Match by visible title — seed sets title to "E2E — {slug}".
    for (const slug of [SEED_COURSES.published.slug, SEED_COURSES.draft.slug]) {
      await expect(
        page.getByText(`E2E — ${slug}`, { exact: false }).first(),
        `expected course "${slug}" visible in org's courses list`,
      ).toBeVisible();
    }
  });
});
