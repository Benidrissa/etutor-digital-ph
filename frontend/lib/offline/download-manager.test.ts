/**
 * The module download saves the module's story when one is already written,
 * so story mode works offline for a downloaded module. A module has one story
 * covering all its units, written on demand when a learner first opens it, so
 * the download only reads the cache (`generate=false`, contract C-4): it must
 * never dispatch a paid generation nobody asked for, nor sit polling for one.
 * Units are no longer asked for stories of their own.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "@/lib/api";
import { moduleStoryUnitKey } from "@/lib/story-course/load";

import { upsertOfflineContent } from "./db";
import { downloadModule, estimateModuleSize, type DownloadProgress } from "./download-manager";
import { prewarmPage } from "./prewarm";

vi.mock("./db", () => ({
  upsertOfflineModule: vi.fn().mockResolvedValue(undefined),
  upsertOfflineContent: vi.fn().mockResolvedValue(undefined),
  getOfflineModule: vi.fn().mockResolvedValue(undefined),
  getOfflineContent: vi.fn().mockResolvedValue(undefined),
  getAllOfflineModules: vi.fn().mockResolvedValue([]),
  deleteOfflineModule: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("./prewarm", () => ({ prewarmPage: vi.fn().mockResolvedValue(undefined) }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);
const upsertContentMock = vi.mocked(upsertOfflineContent);
const prewarmMock = vi.mocked(prewarmPage);

const story = {
  format: "story-course/1",
  id: "module-0f3c-fr",
  chapters: [{ id: "ch1", covers: { unit_number: "1.1", role: "lesson" } }],
  languages: { target: "fr", home: "en" },
};

const STORY_PATH = "/api/v1/story-courses/module/mod-1?language=fr&generate=false";

// What the story endpoint answers in the current test.
let storyAnswer: () => Promise<unknown>;

beforeEach(() => {
  apiFetchMock.mockReset();
  upsertContentMock.mockReset();
  upsertContentMock.mockResolvedValue(undefined);
  prewarmMock.mockClear();
  storyAnswer = async () => story;
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/units")) {
      return {
        units: [
          { unit_number: "1.1", order_index: 0, unit_type: "lesson" },
          { unit_number: "1.2", order_index: 1, unit_type: "quiz" },
          { unit_number: "1.3", order_index: 2, unit_type: "case-study" },
          { unit_number: "1.4", order_index: 3 },
        ],
      };
    }
    if (path.startsWith("/api/v1/story-courses/")) return storyAnswer();
    if (path.startsWith("/api/v1/content/cases/")) throw new ApiError("Not found", 404);
    if (path.startsWith("/api/v1/flashcards/")) return { cards: [] };
    return { ok: true };
  });
});

const requested = () => apiFetchMock.mock.calls.map(([path]) => path);
const storyRequests = () =>
  requested().filter((path) => path.startsWith("/api/v1/story-courses/"));
const storedStories = () =>
  upsertContentMock.mock.calls.map(([row]) => row).filter((row) => row.contentType === "story");
const prewarmed = () => prewarmMock.mock.calls.map(([url]) => url);

describe("downloadModule — module story", () => {
  it("saves the module story once, after the flashcards, reading the cache only", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    // One request for the whole module; no unit asks for a story of its own.
    expect(storyRequests()).toEqual([STORY_PATH]);
    const flashcards = requested().findIndex((path) => path.startsWith("/api/v1/flashcards/"));
    expect(flashcards).toBeGreaterThan(-1);
    expect(requested().indexOf(STORY_PATH)).toBeGreaterThan(flashcards);

    // Stored as the bare document, under the key loadModuleStory reads.
    expect(storedStories()).toHaveLength(1);
    expect(storedStories()[0]).toMatchObject({
      moduleId: "mod-1",
      unitId: moduleStoryUnitKey("mod-1"),
      locale: "fr",
      content: story,
    });

    // The story page is pre-warmed after the unit pages, so it opens offline.
    expect(prewarmed()).toEqual([
      "/fr/modules/mod-1/units/1.1",
      "/fr/modules/mod-1/units/1.2",
      "/fr/modules/mod-1/units/1.3",
      "/fr/modules/mod-1/units/1.4",
      "/fr/modules/mod-1/story",
      "/fr/modules/mod-1",
    ]);

    // One module-level progress tick, with no unit number.
    const storyTicks = ticks.filter((p) => p.currentContentType === "story");
    expect(storyTicks).toEqual([
      { phase: "downloading_content", totalUnits: 4, downloadedUnits: 4, currentContentType: "story" },
    ]);
    expect(ticks.at(-1)?.phase).toBe("complete");
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("asks in the download's language", async () => {
    await downloadModule("mod-1", "en");
    expect(storyRequests()).toEqual([
      "/api/v1/story-courses/module/mod-1?language=en&generate=false",
    ]);
    expect(storedStories()[0]).toMatchObject({ locale: "en" });
    expect(prewarmed()).toContain("/en/modules/mod-1/story");
  });

  it.each([
    ["404 story_not_cached", () => new ApiError("Not cached", 404, undefined, { error: "story_not_cached" })],
    ["404 story_mode_disabled", () => new ApiError("Off", 404, undefined, { error: "story_mode_disabled" })],
    ["404 no_story_content", () => new ApiError("No lesson", 404, undefined, { error: "no_story_content" })],
    ["409 story_unavailable", () => new ApiError("No story", 409, undefined, { error: "story_unavailable" })],
    [
      "403 subscription_required",
      () => new ApiError("Subscribers only", 403, "subscription_required", { code: "subscription_required" }),
    ],
  ])("skips a %s quietly", async (_label, error) => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storyAnswer = async () => {
      throw error();
    };
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    expect(storyRequests()).toEqual([STORY_PATH]);
    expect(storedStories()).toEqual([]);
    expect(prewarmed()).not.toContain("/fr/modules/mod-1/story");
    expect(warn).not.toHaveBeenCalled();
    expect(ticks.at(-1)?.phase).toBe("complete");
    warn.mockRestore();
  });

  it.each([
    ["the 202 envelope", { status: "generating", task_id: "task-story-1" }],
    ["a body that is not a story", { detail: "odd" }],
  ])("stores nothing for %s", async (_label, body) => {
    storyAnswer = async () => body;
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    expect(storedStories()).toEqual([]);
    expect(prewarmed()).not.toContain("/fr/modules/mod-1/story");
    expect(ticks.at(-1)?.phase).toBe("complete");
  });

  it("never polls for a story that is being written", async () => {
    storyAnswer = async () => ({ status: "generating", task_id: "task-story-1" });
    vi.useFakeTimers();
    try {
      const done = downloadModule("mod-1", "fr");
      // Everything else answers at once here; only a story poll would wait
      // on the clock.
      await vi.runAllTimersAsync();
      await done;
    } finally {
      vi.useRealTimers();
    }
    expect(requested().filter((path) => path.startsWith("/api/v1/content/status/"))).toEqual([]);
    // The 202 is not re-fetched either.
    expect(storyRequests()).toHaveLength(1);
  });

  it("keeps going when the story request fails for another reason", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    storyAnswer = async () => {
      throw new ApiError("boom", 500);
    };
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    expect(ticks.at(-1)?.phase).toBe("complete");
    expect(storedStories()).toEqual([]);
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("story of module mod-1"),
      expect.any(ApiError),
    );
    warn.mockRestore();
  });

  it("does not pre-warm the story page when the story could not be stored", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    upsertContentMock.mockImplementation(async (row) => {
      if (row.contentType === "story") throw new Error("QuotaExceededError");
    });
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    expect(prewarmed()).not.toContain("/fr/modules/mod-1/story");
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("store the story of module mod-1"),
      expect.any(Error),
    );
    expect(ticks.at(-1)?.phase).toBe("complete");
    warn.mockRestore();
  });

  it("is cancelled, not failed, when aborted while fetching the story", async () => {
    storyAnswer = async () => {
      throw new DOMException("Aborted", "AbortError");
    };
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });
    expect(ticks.at(-1)?.phase).toBe("cancelled");
    expect(storedStories()).toEqual([]);
  });

  it("budgets for one module story in the size estimate", () => {
    expect(estimateModuleSize(10)).toBe(10 * 50_000 + 30_000 + 150_000);
  });
});
