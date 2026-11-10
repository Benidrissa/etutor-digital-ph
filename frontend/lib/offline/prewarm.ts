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
export const PAGES_CACHE_NAME = "pages-v11-story-fixes";

/**
 * What became of one page:
 * - `cached`: stored;
 * - `gone`: the server said no for good (a unit removed: 404, 410, 403);
 * - `server_error`: the server failed for now (5xx): worth another try;
 * - `network_error`: the request never got through: worth another try;
 * - `store_error`: the page came but could not be stored (storage full): a
 *   retry would only download it again;
 * - `unsupported`: no Cache API here, nothing to do.
 */
export type PrewarmOutcome =
  | "cached"
  | "gone"
  | "server_error"
  | "network_error"
  | "store_error"
  | "unsupported";

/** Outcomes where trying again later can succeed. */
export function prewarmRetryable(outcome: PrewarmOutcome): boolean {
  return outcome === "network_error" || outcome === "server_error";
}

/**
 * Pre-fetch a same-origin page and stash it in the SW page cache so an offline
 * navigation hits cache instead of falling through to /offline.html.
 *
 * Failures are swallowed — pre-warm is best-effort and must never fail a
 * download. It says what happened, so a one-shot migration can tell a page
 * worth another try from one that will never come (#2692).
 */
export async function prewarmPage(url: string): Promise<PrewarmOutcome> {
  if (typeof caches === "undefined") return "unsupported";
  let res: Response;
  try {
    res = await fetch(url, { credentials: "include" });
  } catch {
    return "network_error";
  }
  if (!res.ok) return res.status >= 500 ? "server_error" : "gone";
  try {
    const cache = await caches.open(PAGES_CACHE_NAME);
    await cache.put(url, res.clone());
    return "cached";
  } catch {
    return "store_error";
  }
}

/** Whether a page is in the SW page cache already (so not fetched again). */
export async function isPagePrewarmed(url: string): Promise<boolean> {
  try {
    if (typeof caches === "undefined") return false;
    const cache = await caches.open(PAGES_CACHE_NAME);
    return !!(await cache.match(url));
  } catch {
    return false;
  }
}
