/**
 * Pre-warming stores a page in the service worker's page cache so a downloaded
 * module opens offline. It is best-effort: it must never throw into a
 * download or a sync replay.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PAGES_CACHE_NAME, prewarmPage } from "./prewarm";

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

  it("does not store an error page", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 500 }));
    await prewarmPage("/fr/modules/mod-1");
    expect(cache.put).not.toHaveBeenCalled();
  });

  it("swallows a failed request", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(prewarmPage("/fr/modules/mod-1")).resolves.toBeUndefined();
    expect(cache.put).not.toHaveBeenCalled();
  });
});
