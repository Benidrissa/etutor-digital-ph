/**
 * Pre-warming stores a page in the service worker's page cache so a downloaded
 * module opens offline. It is best-effort: it must never throw into a
 * download or a sync replay.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PAGES_CACHE_NAME, isPagePrewarmed, prewarmPage } from "./prewarm";

const cache = { put: vi.fn() };
const open = vi.fn(async () => cache);
const fetchMock = vi.fn();

beforeEach(() => {
  cache.put.mockReset();
  open.mockClear();
  fetchMock.mockReset();
  vi.stubGlobal("caches", { open });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("prewarmPage", () => {
  it("does nothing where the Cache API is missing", async () => {
    vi.stubGlobal("caches", undefined);
    await prewarmPage("/fr/modules/mod-1");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("stores a page that loaded under its URL in the pages cache", async () => {
    const response = new Response("<html></html>", { status: 200 });
    fetchMock.mockResolvedValue(response);

    await prewarmPage("/fr/modules/mod-1/story");

    expect(open).toHaveBeenCalledWith(PAGES_CACHE_NAME);
    expect(fetchMock).toHaveBeenCalledWith("/fr/modules/mod-1/story", { credentials: "include" });
    expect(cache.put).toHaveBeenCalledTimes(1);
    expect(cache.put.mock.calls[0][0]).toBe("/fr/modules/mod-1/story");
  });

  it("says what became of the page: stored, gone for good, or worth another try (#2692)", async () => {
    fetchMock.mockResolvedValue(new Response("<html></html>", { status: 200 }));
    await expect(prewarmPage("/fr/modules/mod-1")).resolves.toBe("cached");
    // A unit removed from the course: it will never come.
    fetchMock.mockResolvedValue(new Response("nope", { status: 404 }));
    await expect(prewarmPage("/fr/modules/mod-1/units/1.6")).resolves.toBe("gone");
    // A deploy in progress: try again later.
    fetchMock.mockResolvedValue(new Response("nope", { status: 503 }));
    await expect(prewarmPage("/fr/modules/mod-1")).resolves.toBe("server_error");
    // Storage full: downloading it again would not help.
    fetchMock.mockResolvedValue(new Response("<html></html>", { status: 200 }));
    cache.put.mockRejectedValueOnce(new DOMException("full", "QuotaExceededError"));
    await expect(prewarmPage("/fr/modules/mod-1")).resolves.toBe("store_error");
  });

  it("knows a page it stored already", async () => {
    const match = vi.fn(async (url: string) => (url === "/fr/modules/mod-1" ? new Response("x") : undefined));
    vi.stubGlobal("caches", { open: vi.fn(async () => ({ ...cache, match })) });
    await expect(isPagePrewarmed("/fr/modules/mod-1")).resolves.toBe(true);
    await expect(isPagePrewarmed("/fr/modules/mod-2")).resolves.toBe(false);
  });

  it("does not store an error page", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 500 }));
    await prewarmPage("/fr/modules/mod-1");
    expect(cache.put).not.toHaveBeenCalled();
  });

  it("swallows a failed request", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(prewarmPage("/fr/modules/mod-1")).resolves.toBe("network_error");
    expect(cache.put).not.toHaveBeenCalled();
  });
});
