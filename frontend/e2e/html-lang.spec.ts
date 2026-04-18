import { test, expect } from "@playwright/test";

/**
 * Regression guard for issue #1617 — every rendered page must carry the
 * right `<html lang>`. Pre-fix, it was always empty (WCAG A failure).
 */
test.describe("html lang attribute", () => {
  test("/fr/* pages set lang='fr'", async ({ page }) => {
    await page.goto("/fr/courses");
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBe("fr");
  });

  test("/en/* pages set lang='en'", async ({ page }) => {
    await page.goto("/en/courses");
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBe("en");
  });
});
