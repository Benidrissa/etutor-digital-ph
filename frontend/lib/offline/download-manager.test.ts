/**
 * The module download includes each lesson's story, so story mode works
 * offline for a downloaded module — and only lessons are asked for one.
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
        ],
      };
    }
    if (path.startsWith("/api/v1/story-courses/unit/")) {
      if (path.includes("/1.4?")) {
        throw new ApiError("No valid story", 409, undefined, { error: "story_unavailable" });
      }
      return story;
    }
    if (path.startsWith("/api/v1/content/cases/")) throw new ApiError("Not found", 404);
    return { ok: true };
  });
});

describe("downloadModule — lesson stories", () => {
  it("downloads a story for lesson units only, with a progress tick", async () => {
    // The 409 on unit 1.4 is logged as a skipped item; keep the output quiet.
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const ticks: DownloadProgress[] = [];
    await downloadModule("mod-1", "fr", { onProgress: (p) => ticks.push(p) });
    warn.mockRestore();

    const storyPaths = apiFetchMock.mock.calls
      .map(([path]) => path)
      .filter((path) => path.startsWith("/api/v1/story-courses/unit/"));
    // 1.1 is a lesson and 1.4 is untyped (rendered by the lesson viewer);
    // the quiz and case-study units have no Story tab.
    expect(storyPaths).toEqual([
      "/api/v1/story-courses/unit/mod-1/1.1?language=fr",
      "/api/v1/story-courses/unit/mod-1/1.4?language=fr",
    ]);

    const storyTicks = ticks.filter((p) => p.currentContentType === "story").map((p) => p.currentUnit);
    expect(storyTicks).toEqual(["1.1", "1.4"]);

    const stored = upsertContentMock.mock.calls.map(([row]) => row).filter((row) => row.contentType === "story");
    expect(stored).toHaveLength(1);
    expect(stored[0]).toMatchObject({ moduleId: "mod-1", unitId: "1.1", locale: "fr", content: story });

    // A unit with no valid story (409) does not fail the download.
    expect(ticks.at(-1)?.phase).toBe("complete");
  });

  it("budgets for the story in the size estimate", () => {
    expect(estimateModuleSize(10)).toBe(10 * 80_000 + 30_000);
  });
});
