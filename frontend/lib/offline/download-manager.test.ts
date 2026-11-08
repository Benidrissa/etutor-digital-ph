/**
 * The module download saves each lesson's story when one is already written,
 * so story mode works offline for a downloaded module. Stories are written on
 * demand (when a learner opens the tab), so the download only reads the cache
 * (`generate=false`, contract X1): it must never dispatch a paid generation
 * for a lesson nobody opened, nor sit polling for one.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch, ApiError } from "@/lib/api";

import { upsertOfflineContent } from "./db";
import { downloadModule, estimateModuleSize, type DownloadProgress } from "./download-manager";

vi.mock("./db", () => ({
  upsertOfflineModule: vi.fn().mockResolvedValue(undefined),
  upsertOfflineContent: vi.fn().mockResolvedValue(undefined),
  getOfflineModule: vi.fn().mockResolvedValue(undefined),
  getAllOfflineModules: vi.fn().mockResolvedValue([]),
  deleteOfflineModule: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

const apiFetchMock = vi.mocked(apiFetch);
const upsertContentMock = vi.mocked(upsertOfflineContent);

const story = { format: "story-course/1", id: "lesson-ab-fr", chapters: [], languages: { target: "fr", home: "en" } };

beforeEach(() => {
  apiFetchMock.mockReset();
  upsertContentMock.mockClear();
  apiFetchMock.mockImplementation(async (path: string) => {
    if (path.endsWith("/units")) {
      return {
        units: [
          { unit_number: "1.1", order_index: 0, unit_type: "lesson" },
          { unit_number: "1.2", order_index: 1, unit_type: "quiz" },
          { unit_number: "1.3", order_index: 2, unit_type: "case-study" },
          { unit_number: "1.4", order_index: 3 },
          { unit_number: "1.5", order_index: 4, unit_type: "lesson" },
          { unit_number: "1.6", order_index: 5, unit_type: "lesson" },
        ],
      };
    }
    if (path.startsWith("/api/v1/story-courses/unit/")) {
      if (path.includes("/1.4?")) {
        throw new ApiError("No valid story", 409, undefined, { error: "story_unavailable" });
      }
      if (path.includes("/1.5?")) {
        throw new ApiError("Story not cached", 404, undefined, { error: "story_not_cached" });
      }
      if (path.includes("/1.6?")) {
        // An older backend that ignores generate=false and starts writing.
        return { status: "generating", task_id: "task-story-1.6" };
      }
      return story;
    }
    if (path.startsWith("/api/v1/content/cases/")) throw new ApiError("Not found", 404);
    return { ok: true };
  });
});

describe("downloadModule — lesson stories", () => {
  it("asks lesson units only for a cached story, with a progress tick", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });

    const storyPaths = apiFetchMock.mock.calls
      .map(([path]) => path)
      .filter((path) => path.startsWith("/api/v1/story-courses/unit/"));
    // 1.1, 1.5 and 1.6 are lessons and 1.4 is untyped (rendered by the lesson
    // viewer); the quiz and case-study units have no Story tab. Every request
    // reads the cache only.
    expect(storyPaths).toEqual([
      "/api/v1/story-courses/unit/mod-1/1.1?language=fr&generate=false",
      "/api/v1/story-courses/unit/mod-1/1.4?language=fr&generate=false",
      "/api/v1/story-courses/unit/mod-1/1.5?language=fr&generate=false",
      "/api/v1/story-courses/unit/mod-1/1.6?language=fr&generate=false",
    ]);

    const storyTicks = ticks.filter((p) => p.currentContentType === "story").map((p) => p.currentUnit);
    expect(storyTicks).toEqual(["1.1", "1.4", "1.5", "1.6"]);

    // Only the cached story is saved: not the 409, the 404 story_not_cached,
    // nor the 202 envelope.
    const stored = upsertContentMock.mock.calls.map(([row]) => row).filter((row) => row.contentType === "story");
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ moduleId: "mod-1", unitId: "1.1", locale: "fr", content: story });

    // Skipped stories are expected, not warnings, and do not fail the download.
    expect(warn).not.toHaveBeenCalledWith(expect.stringContaining("story"), expect.anything());
    expect(ticks.at(-1)?.phase).toBe("complete");
    warn.mockRestore();
  });

  it("never polls for a story that is being written", async () => {
    vi.useFakeTimers();
    try {
      const done = downloadModule("mod-1", "fr");
      // Lessons, quizzes and cases answer at once here; only a story poll
      // would wait on the clock.
      await vi.runAllTimersAsync();
      await done;
    } finally {
      vi.useRealTimers();
    }
    const statusPolls = apiFetchMock.mock.calls
      .map(([path]) => path)
      .filter((path) => path.startsWith("/api/v1/content/status/"));
    expect(statusPolls).toEqual([]);
    // One request per lesson unit: the 202 is not re-fetched either.
    const storyPaths = apiFetchMock.mock.calls
      .map(([path]) => path)
      .filter((path) => path.startsWith("/api/v1/story-courses/unit/mod-1/1.6?"));
    expect(storyPaths).toHaveLength(1);
  });

  it("keeps going when a story request fails for another reason", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const base = apiFetchMock.getMockImplementation()!;
    apiFetchMock.mockImplementation(async (path: string, init?: RequestInit) => {
      if (path.includes("/story-courses/unit/mod-1/1.1?")) throw new ApiError("boom", 500);
      return base(path, init);
    });
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });
    expect(ticks.at(-1)?.phase).toBe("complete");
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("story for 1.1"), expect.any(ApiError));
    warn.mockRestore();
  });

  it("budgets for the story in the size estimate", () => {
    expect(estimateModuleSize(10)).toBe(10 * 80_000 + 30_000);
  });
});
