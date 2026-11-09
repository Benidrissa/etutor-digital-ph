/**
 * The module story URLs (contract C-5). The story page and the module
 * downloader must request the very same path, and only the downloader may
 * ask for a cache-only read.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "../api";
import * as storyApi from "./api";
import {
  getModuleStoryStatus,
  isStoryDocument,
  isStoryGenerating,
  moduleStoryPath,
  moduleStoryStatusPath,
  storyErrorCode,
} from "./api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return { ...actual, apiFetch: vi.fn() };
});

const MODULE_ID = "6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b";

afterEach(() => {
  vi.mocked(apiFetch).mockReset();
});

describe("moduleStoryPath", () => {
  it("generates on demand by default", () => {
    expect(moduleStoryPath(MODULE_ID, "fr")).toBe(
      `/api/v1/story-courses/module/${MODULE_ID}?language=fr`,
    );
    expect(moduleStoryPath(MODULE_ID, "en", { generate: true })).toBe(
      `/api/v1/story-courses/module/${MODULE_ID}?language=en`,
    );
  });

  it("reads the cache only with generate: false", () => {
    expect(moduleStoryPath(MODULE_ID, "en", { generate: false })).toBe(
      `/api/v1/story-courses/module/${MODULE_ID}?language=en&generate=false`,
    );
  });

  it("encodes the module id", () => {
    expect(moduleStoryPath("a/b c", "fr")).toBe(
      "/api/v1/story-courses/module/a%2Fb%20c?language=fr",
    );
  });
});

describe("moduleStoryStatusPath", () => {
  it("points at the status route, which never dispatches", () => {
    expect(moduleStoryStatusPath(MODULE_ID, "fr")).toBe(
      `/api/v1/story-courses/module/${MODULE_ID}/status?language=fr`,
    );
  });

  it("is what getModuleStoryStatus fetches", async () => {
    const status = {
      state: "ready",
      task_id: null,
      chapters: 4,
      revision: "0123456789abcdef",
      access: "ok",
    };
    vi.mocked(apiFetch).mockResolvedValue(status);
    await expect(getModuleStoryStatus(MODULE_ID, "en")).resolves.toEqual(status);
    expect(apiFetch).toHaveBeenCalledWith(
      `/api/v1/story-courses/module/${MODULE_ID}/status?language=en`,
    );
  });
});

describe("response guards (unchanged)", () => {
  it("tells a document from the 202 envelope", () => {
    const envelope = { status: "generating", task_id: "t-1" };
    expect(isStoryGenerating(envelope)).toBe(true);
    expect(isStoryDocument(envelope)).toBe(false);
    expect(isStoryDocument({ chapters: [], languages: { target: "fr", home: "en" } })).toBe(
      true,
    );
  });

  it("reads detail.error whatever the status", () => {
    expect(storyErrorCode({ status: 404, detail: { error: "story_mode_disabled" } })).toBe(
      "story_mode_disabled",
    );
    expect(storyErrorCode({ status: 403, detail: { code: "subscription_required" } })).toBe(
      undefined,
    );
  });
});

describe("the per-lesson story", () => {
  it("has no path helper left: the /story-courses/unit/ route is gone", () => {
    expect(storyApi).not.toHaveProperty("unitStoryPath");
  });
});
