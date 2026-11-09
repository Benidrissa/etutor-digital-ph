/**
 * Service worker page cache pre-warming for downloaded modules.
 *
 * Kept apart from the downloader on purpose: the sync manager runs in the
 * (app) layout (through the offline indicator) and re-warms pages after a
 * replay. Importing this from download-manager.ts pulled the whole downloader,
 * and the story-course helpers it uses, into the chunk every page loads.
 */

// Cache name MUST stay aligned with `pages-${CACHE_VERSION}` in frontend/sw.ts.
// Bump both together when changing.
export const PAGES_CACHE_NAME = "pages-v9-api-keys-tab";

/**
 * Pre-fetch a same-origin page and stash it in the SW page cache so an offline
 * navigation hits cache instead of falling through to /offline.html.
 *
 * Failures are swallowed — pre-warm is best-effort and must never fail a
 * download.
 */
export async function prewarmPage(url: string): Promise<void> {
  try {
    if (typeof caches === "undefined") return;
    const cache = await caches.open(PAGES_CACHE_NAME);
    const res = await fetch(url, { credentials: "include" });
    if (res.ok) {
      await cache.put(url, res.clone());
    }
  } catch {
    // best-effort
  }
}
