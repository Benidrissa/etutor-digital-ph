/**
 * The service worker's API cache (StaleWhileRevalidate) must leave story-course
 * responses alone. A module story is gated per learner and rewritten whenever
 * one of its lessons or quizzes changes; its offline copy is the IndexedDB one
 * the module download saves. Replayed from the SW cache, a regenerated story,
 * or one the learner may no longer open, would come back for up to a day.
 *
 * Serwist is replaced by recording classes, so this reads the real runtime
 * caching rules sw.ts builds without running a service worker.
 */

import { describe, expect, it, vi } from "vitest";
import { CacheFirst, NetworkFirst, StaleWhileRevalidate } from "serwist";

import { PAGES_CACHE_NAME } from "@/lib/offline/prewarm";

import "./sw";

type Matcher = (context: { url: URL; request: Request }) => boolean;
interface RuntimeCaching {
  matcher: RegExp | Matcher;
  handler: { options: { cacheName?: string } };
}

const recorded = vi.hoisted(() => ({
  options: undefined as undefined | { runtimeCaching: RuntimeCaching[] },
}));

vi.mock("serwist", () => {
  class Strategy {
    constructor(public options: Record<string, unknown>) {}
  }
  class NetworkFirst extends Strategy {}
  class CacheFirst extends Strategy {}
  class StaleWhileRevalidate extends Strategy {}
  class ExpirationPlugin {
    constructor(public options: Record<string, unknown>) {}
  }
  class Serwist {
    constructor(options: { runtimeCaching: RuntimeCaching[] }) {
      recorded.options = options;
    }
    addEventListeners() {}
  }
  return { Serwist, NetworkFirst, CacheFirst, StaleWhileRevalidate, ExpirationPlugin };
});

function rule(handler: abstract new (...args: never[]) => unknown): RuntimeCaching {
  const found = recorded.options?.runtimeCaching.find((entry) => entry.handler instanceof handler);
  if (!found) throw new Error(`no ${handler.name} rule`);
  return found;
}

function apiRule(): RuntimeCaching {
  const found = recorded.options?.runtimeCaching.find((entry) =>
    entry.handler.options.cacheName?.startsWith("api-responses-"),
  );
  if (!found) throw new Error("no API rule");
  return found;
}

function apiCacheTakes(path: string, method = "GET"): boolean {
  const matcher = apiRule().matcher as Matcher;
  return matcher({
    url: new URL(path, "https://sira.example"),
    request: { method } as Request,
  });
}

/** The first rule that takes a GET of `path`, as the service worker picks it. */
function ruleFor(path: string): RuntimeCaching | undefined {
  const url = new URL(path, "https://sira.example");
  return recorded.options?.runtimeCaching.find((entry) =>
    entry.matcher instanceof RegExp
      ? entry.matcher.test(url.href)
      : entry.matcher({ url, request: { method: "GET", mode: "cors" } as Request }),
  );
}

describe("service worker API cache", () => {
  it.each([
    "/api/v1/story-courses/module/7f0c2a52-8f1c-4c1e-9d55-0d6c2f1b9e10?language=fr",
    "/api/v1/story-courses/module/7f0c2a52-8f1c-4c1e-9d55-0d6c2f1b9e10?language=en&generate=false",
    "/api/v1/story-courses/module/7f0c2a52-8f1c-4c1e-9d55-0d6c2f1b9e10/status?language=fr",
    "/api/v1/story-courses/week-1-fr",
    "/api/v1/story-courses/unit/mod-1/1.2?language=fr",
  ])("does not cache %s", (path) => {
    expect(apiCacheTakes(path)).toBe(false);
  });

  it("still caches other learner content", () => {
    expect(apiCacheTakes("/api/v1/content/lessons/mod-1/1.1?language=fr&level=1&country=CI")).toBe(
      true,
    );
    expect(apiCacheTakes("/api/v1/flashcards/modules/mod-1?language=fr&level=1")).toBe(true);
  });

  it("keeps its earlier exclusions", () => {
    expect(apiCacheTakes("/api/v1/progress/modules/mod-1/detail")).toBe(false);
    expect(apiCacheTakes("/api/v1/content/status/task-1")).toBe(false);
    expect(apiCacheTakes("/api/v1/content/lessons/mod-1/1.1", "POST")).toBe(false);
  });

  it("pre-warmed pages land in the cache the navigation rule reads", () => {
    expect(rule(NetworkFirst).handler.options.cacheName).toBe(PAGES_CACHE_NAME);
  });
});

describe("service worker story media cache (#2681)", () => {
  const ART = "/api/v1/story-art/3f2c9a1e-0b7d-4c55-9e2a-1d2f3a4b5c6d/data";
  const STICKER = "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data";
  const FIGURE = "/api/v1/source-images/7e8f9a0b-1c2d-4e3f-8a9b-0c1d2e3f4a5b/data?lang=fr";

  it("keeps story art and prop pictures in a stable cache, cache first", () => {
    for (const path of [ART, `${STICKER}?size=s`]) {
      const found = ruleFor(path);
      expect(found?.handler).toBeInstanceOf(CacheFirst);
      // Not versioned: a downloaded story keeps its pictures across updates.
      expect(found?.handler.options.cacheName).toBe("story-media-v1");
    }
  });

  it("refreshes course figures behind the cached copy", () => {
    const found = ruleFor(FIGURE);
    expect(found?.handler).toBeInstanceOf(StaleWhileRevalidate);
    expect(found?.handler.options.cacheName).toBe("story-media-v1");
  });

  it("leaves other paths of those routes to the API rule", () => {
    expect(ruleFor("/api/v1/source-images/7e8f9a0b-1c2d-4e3f-8a9b-0c1d2e3f4a5b")?.handler.options.cacheName).toMatch(
      /^api-responses-/,
    );
  });

  it("bumps the page cache with the service worker", () => {
    expect(PAGES_CACHE_NAME).toBe("pages-v10-story-media");
  });
});
