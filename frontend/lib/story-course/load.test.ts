/**
 * loadModuleStory (contract C-5): network first, the IndexedDB copy only when
 * the request cannot get through, and only the bare document is stored.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api";
import { OfflineContentNotAvailable } from "@/lib/offline/content-loader";
import { getOfflineContent, upsertOfflineContent } from "@/lib/offline/db";

import { moduleStoryPath } from "./api";
import { loadModuleStory, moduleStoryUnitKey } from "./load";
import type { StoryCourse } from "./types";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock("@/lib/offline/db", () => ({
  getOfflineContent: vi.fn(),
  upsertOfflineContent: vi.fn(),
}));

const apiFetchMock = vi.mocked(apiFetch);
const getOfflineContentMock = vi.mocked(getOfflineContent);
const upsertOfflineContentMock = vi.mocked(upsertOfflineContent);

const MODULE_ID = "6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b";
const UNIT_KEY = `__module_${MODULE_ID}__`;

function story(): StoryCourse {
  return {
    format: "story-course/1",
    id: "module-6f1c2d3e4b5a69788a9b0c1d2e3f4a5b-fr",
    course: "Santé publique",
    week: 1,
    title: { en: "Hygiene", fr: "Hygiène" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "{child}" },
    objectives: [],
    cast: [],
    chapters: [{ id: "ch1", title: { en: "One", fr: "Un" }, scenes: [] }],
    questions: [],
  };
}

function setOnline(online: boolean) {
  Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => online });
}

beforeEach(() => {
  apiFetchMock.mockReset();
  getOfflineContentMock.mockReset();
  upsertOfflineContentMock.mockReset();
  upsertOfflineContentMock.mockResolvedValue(undefined);
  setOnline(true);
});

afterEach(() => {
  setOnline(true);
});

describe("loadModuleStory", () => {
  it("keys the offline copy under the module's pseudo-unit", () => {
    expect(moduleStoryUnitKey(MODULE_ID)).toBe(UNIT_KEY);
  });

  it("fetches the module story path and stores the bare document", async () => {
    const doc = story();
    apiFetchMock.mockResolvedValue(doc);

    await expect(loadModuleStory(MODULE_ID, "fr")).resolves.toBe(doc);

    expect(apiFetchMock).toHaveBeenCalledWith(moduleStoryPath(MODULE_ID, "fr"));
    expect(upsertOfflineContentMock).toHaveBeenCalledTimes(1);
    const stored = upsertOfflineContentMock.mock.calls[0][0];
    expect(stored).toMatchObject({
      unitId: UNIT_KEY,
      moduleId: MODULE_ID,
      contentType: "story",
      locale: "fr",
    });
    expect(stored.content).toBe(doc);
    expect(getOfflineContentMock).not.toHaveBeenCalled();
  });

  it("returns the 202 envelope without storing it", async () => {
    const envelope = { status: "generating", task_id: "task-1" };
    apiFetchMock.mockResolvedValue(envelope);

    await expect(loadModuleStory(MODULE_ID, "en")).resolves.toEqual(envelope);
    expect(upsertOfflineContentMock).not.toHaveBeenCalled();
  });

  it("rejects a body that is neither a story nor the envelope", async () => {
    apiFetchMock.mockResolvedValue({ detail: "odd" });
    await expect(loadModuleStory(MODULE_ID, "en")).rejects.toThrow(/Unexpected/);
    expect(upsertOfflineContentMock).not.toHaveBeenCalled();
  });

  it("still returns the story when IndexedDB refuses the write", async () => {
    const doc = story();
    apiFetchMock.mockResolvedValue(doc);
    upsertOfflineContentMock.mockRejectedValue(new Error("QuotaExceededError"));
    await expect(loadModuleStory(MODULE_ID, "fr")).resolves.toBe(doc);
  });

  it("reads the downloaded copy when offline, without a request", async () => {
    setOnline(false);
    const doc = story();
    getOfflineContentMock.mockResolvedValue({
      unitId: UNIT_KEY,
      moduleId: MODULE_ID,
      contentType: "story",
      locale: "fr",
      content: doc,
      cachedAt: 1,
    });

    await expect(loadModuleStory(MODULE_ID, "fr")).resolves.toEqual(doc);
    expect(getOfflineContentMock).toHaveBeenCalledWith(MODULE_ID, UNIT_KEY, "story", "fr");
    expect(apiFetchMock).not.toHaveBeenCalled();
  });

  it("throws OfflineContentNotAvailable offline with no copy", async () => {
    setOnline(false);
    getOfflineContentMock.mockResolvedValue(undefined);
    await expect(loadModuleStory(MODULE_ID, "fr")).rejects.toBeInstanceOf(
      OfflineContentNotAvailable,
    );
  });

  it("ignores a cached envelope or junk offline", async () => {
    setOnline(false);
    getOfflineContentMock.mockResolvedValue({
      unitId: UNIT_KEY,
      moduleId: MODULE_ID,
      contentType: "story",
      locale: "fr",
      content: { status: "generating", task_id: "t" },
      cachedAt: 1,
    });
    await expect(loadModuleStory(MODULE_ID, "fr")).rejects.toBeInstanceOf(
      OfflineContentNotAvailable,
    );
  });

  it("falls back to the copy when the request never gets through", async () => {
    const doc = story();
    apiFetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    getOfflineContentMock.mockResolvedValue({
      unitId: UNIT_KEY,
      moduleId: MODULE_ID,
      contentType: "story",
      locale: "en",
      content: doc,
      cachedAt: 1,
    });

    await expect(loadModuleStory(MODULE_ID, "en")).resolves.toEqual(doc);
    expect(getOfflineContentMock).toHaveBeenCalledWith(MODULE_ID, UNIT_KEY, "story", "en");
  });

  it("says offline when the request fails and nothing was downloaded", async () => {
    apiFetchMock.mockRejectedValue(new TypeError("Load failed"));
    getOfflineContentMock.mockResolvedValue(undefined);
    await expect(loadModuleStory(MODULE_ID, "en")).rejects.toBeInstanceOf(
      OfflineContentNotAvailable,
    );
  });

  it.each([
    [403, "subscription_required"],
    [409, "story_unavailable"],
    [404, "story_mode_disabled"],
  ])("never hides a %i answer behind the cached copy", async (status, code) => {
    const err = new ApiError(code, status, code === "subscription_required" ? code : undefined, {
      error: code,
    });
    apiFetchMock.mockRejectedValue(err);

    await expect(loadModuleStory(MODULE_ID, "fr")).rejects.toBe(err);
    expect(getOfflineContentMock).not.toHaveBeenCalled();
  });
});
