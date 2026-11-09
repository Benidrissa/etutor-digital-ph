/**
 * Module story resume progress in localStorage (contract C-5). Whatever the
 * storage does — missing, corrupt, an older format, throwing — the story must
 * still open, just from the first chapter.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  chapterKey,
  chapterLocalId,
  completedChapterCount,
  emptyStoryProgress,
  firstIncompleteChapter,
  moduleStoryId,
  readStoryProgress,
  storyProgressKey,
  withChapterDone,
  writeStoryProgress,
} from "./progress";
import type { Chapter } from "./types";

const STORY_ID = "module-6f1c2d3e4b5a69788a9b0c1d2e3f4a5b-fr";
const USER = "user-1";

function chapter(id: string, unitId?: string): Chapter {
  return {
    id,
    title: { en: id, fr: id },
    scenes: [],
    covers: unitId
      ? {
          module_unit_id: unitId,
          unit_number: "1.1",
          unit_type: "lesson",
          role: "lesson",
          status: "ready",
          completes_unit: true,
          max_points: 2,
        }
      : undefined,
  };
}

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("story progress", () => {
  it("keys the progress by learner and story", () => {
    expect(storyProgressKey(STORY_ID, USER)).toBe(`sira.story.progress:${USER}:${STORY_ID}`);
  });

  it("keeps each learner's progress apart on a shared phone", () => {
    writeStoryProgress(STORY_ID, "learner-a", withChapterDone(emptyStoryProgress(), "unit-a", 3));
    expect(readStoryProgress(STORY_ID, "learner-b")).toEqual(emptyStoryProgress());
    expect(readStoryProgress(STORY_ID, "learner-a").completedUnits).toEqual(["unit-a"]);
  });

  it("neither reads nor saves without a known learner", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    writeStoryProgress(STORY_ID, null, withChapterDone(emptyStoryProgress(), "unit-a", 3));
    expect(setItem).not.toHaveBeenCalled();
    window.localStorage.setItem(
      `sira.story.progress:${STORY_ID}`,
      JSON.stringify({ v: 1, completedUnits: ["unit-a"], points: {} }),
    );
    expect(readStoryProgress(STORY_ID, null)).toEqual(emptyStoryProgress());
    expect(readStoryProgress(STORY_ID, undefined)).toEqual(emptyStoryProgress());
  });

  it("derives the backend's module story id from the module uuid", () => {
    expect(moduleStoryId("6F1C2D3E-4B5A-6978-8A9B-0C1D2E3F4A5B", "fr")).toBe(STORY_ID);
    expect(moduleStoryId("6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b", "en")).toBe(
      "module-6f1c2d3e4b5a69788a9b0c1d2e3f4a5b-en",
    );
  });

  it("round-trips through localStorage", () => {
    const progress = withChapterDone(emptyStoryProgress(), "unit-a", 3);
    writeStoryProgress(STORY_ID, USER, progress);
    expect(JSON.parse(window.localStorage.getItem(storyProgressKey(STORY_ID, USER))!)).toEqual({
      v: 1,
      completedUnits: ["unit-a"],
      points: { "unit-a": 3 },
    });
    expect(readStoryProgress(STORY_ID, USER)).toEqual(progress);
  });

  it.each([
    ["missing", null],
    ["corrupt JSON", "{not json"],
    ["another version", JSON.stringify({ v: 2, completedUnits: ["a"], points: {} })],
    ["not an object", JSON.stringify("hello")],
  ])("starts empty when the value is %s", (_label, raw) => {
    if (raw !== null) window.localStorage.setItem(storyProgressKey(STORY_ID, USER), raw);
    expect(readStoryProgress(STORY_ID, USER)).toEqual(emptyStoryProgress());
  });

  it("drops malformed entries but keeps the good ones", () => {
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER),
      JSON.stringify({ v: 1, completedUnits: ["a", 7, "a", "b"], points: { a: 2, b: "x", c: -1 } }),
    );
    expect(readStoryProgress(STORY_ID, USER)).toEqual({
      v: 1,
      completedUnits: ["a", "b"],
      points: { a: 2 },
    });
  });

  it("survives storage that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(readStoryProgress(STORY_ID, USER)).toEqual(emptyStoryProgress());
    expect(() => writeStoryProgress(STORY_ID, USER, emptyStoryProgress())).not.toThrow();
  });

  it("lists a unit once and keeps its best score", () => {
    let progress = withChapterDone(emptyStoryProgress(), "a", 4);
    progress = withChapterDone(progress, "a", 1);
    expect(progress).toEqual({ v: 1, completedUnits: ["a"], points: { a: 4 } });
    progress = withChapterDone(progress, "a", 6);
    expect(progress.points.a).toBe(6);
  });

  it("does not mutate the progress it is given", () => {
    const before = emptyStoryProgress();
    withChapterDone(before, "a", 1);
    expect(before).toEqual(emptyStoryProgress());
  });

  it("keys a chapter by its unit, else by its own id", () => {
    expect(chapterKey(chapter("ch1", "unit-a"))).toBe("unit-a");
    expect(chapterKey(chapter("ch9"))).toBe("ch9");
  });

  it("finds the first chapter not finished yet", () => {
    const chapters = [chapter("ch1", "a"), chapter("ch2", "b"), chapter("ch3", "c")];
    expect(firstIncompleteChapter(chapters, emptyStoryProgress())).toBe(0);
    const progress = { v: 1 as const, completedUnits: ["a", "c"], points: {} };
    expect(firstIncompleteChapter(chapters, progress)).toBe(1);
    expect(completedChapterCount(chapters, progress)).toBe(2);
    const all = { v: 1 as const, completedUnits: ["a", "b", "c"], points: {} };
    expect(firstIncompleteChapter(chapters, all)).toBe(-1);
  });

  it("ignores units the story no longer has", () => {
    const chapters = [chapter("ch1", "a"), chapter("ch2", "b")];
    const progress = { v: 1 as const, completedUnits: ["gone", "a"], points: {} };
    expect(firstIncompleteChapter(chapters, progress)).toBe(1);
    expect(completedChapterCount(chapters, progress)).toBe(1);
  });
});

describe("chapterLocalId", () => {
  it("strips the assembler's u{key}- namespace and nothing else", () => {
    expect(chapterLocalId("u1_1-E1")).toBe("E1");
    expect(chapterLocalId("u2_10-E-2")).toBe("E-2");
    expect(chapterLocalId("uA_1_2-situation-q3")).toBe("situation-q3");
    // Not namespaced: left alone.
    expect(chapterLocalId("E1")).toBe("E1");
    expect(chapterLocalId("u1_1-")).toBe("u1_1-");
  });
});
