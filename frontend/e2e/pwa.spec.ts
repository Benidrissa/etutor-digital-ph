import { test, expect } from "@playwright/test";

/**
 * Regression guard for issue #1615 — without @serwist/next wiring in
 * next.config.ts, `/sw.js` returns Next's 404 HTML and `getRegistrations()`
 * is empty. If either drifts back to that state this test fails in CI.
 */
test.describe("PWA service worker", () => {
  test("/sw.js is served as JavaScript", async ({ request }) => {
    const res = await request.get("/sw.js");
    expect(res.status()).toBe(200);
    const contentType = res.headers()["content-type"] || "";
    expect(contentType).toMatch(/javascript/);
    // Sanity: the file should actually look like an SW (registers some handler).
    const body = await res.text();
    expect(body).toMatch(/self\.|serviceWorker|workbox|serwist/i);
  });

  test("service worker registers on page load", async ({ page }) => {
    await page.goto("/fr/courses");
    // Wait for the ServiceWorkerRegister effect to fire + SW to install.
    await page.waitForFunction(
      async () => {
        if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) {
          return false;
        }
        const regs = await navigator.serviceWorker.getRegistrations();
        return regs.length >= 1;
      },
      null,
      { timeout: 10_000 },
    );
    const count = await page.evaluate(async () => {
      const regs = await navigator.serviceWorker.getRegistrations();
      return regs.length;
    });
    expect(count).toBeGreaterThanOrEqual(1);
  });
});
