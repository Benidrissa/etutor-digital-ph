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
import { NetworkFirst, StaleWhileRevalidate } from "serwist";

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

function apiCacheTakes(path: string, method = "GET"): boolean {
  const matcher = rule(StaleWhileRevalidate).matcher as Matcher;
  return matcher({
    url: new URL(path, "https://sira.example"),
    request: { method } as Request,
  });
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
