/**
 * Completing a lesson unit on a flaky connection: `navigator.onLine` says
 * online, the POST dies anyway. The completion must be queued for background
 * sync, as it is offline, not dropped. A 4xx is a real refusal and is not.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api";
import { addOfflineAction } from "@/lib/offline/db";

import { completeLessonUnit, isTransientFailure } from "./complete-lesson";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock("@/lib/offline/db", () => ({
  addOfflineAction: vi.fn().mockResolvedValue(1),
}));

const apiFetchMock = vi.mocked(apiFetch);
const addOfflineActionMock = vi.mocked(addOfflineAction);

const queued = {
  actionType: "case_study_complete",
  payload: { module_id: "mod-1", unit_id: "1.2" },
};

beforeEach(() => {
  apiFetchMock.mockReset();
  addOfflineActionMock.mockClear();
});

describe("completeLessonUnit", () => {
  it("POSTs the completion when online", async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    await expect(completeLessonUnit("mod-1", "1.2", { online: true })).resolves.toBe("recorded");
    expect(apiFetchMock).toHaveBeenCalledWith("/api/v1/progress/complete-lesson", {
      method: "POST",
      body: JSON.stringify({ module_id: "mod-1", unit_id: "1.2" }),
    });
    expect(addOfflineActionMock).not.toHaveBeenCalled();
  });

  it("queues it when offline, without trying the network", async () => {
    await expect(completeLessonUnit("mod-1", "1.2", { online: false })).resolves.toBe("queued");
    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(addOfflineActionMock).toHaveBeenCalledTimes(1);
    expect(addOfflineActionMock).toHaveBeenCalledWith(queued);
  });

  it.each([
    ["a dropped connection", new TypeError("Failed to fetch")],
    ["Safari's dropped connection", new TypeError("Load failed")],
    ["a timeout", new DOMException("The operation timed out.", "TimeoutError")],
    ["a server error", new ApiError("Bad gateway", 502)],
    ["an unavailable server", new ApiError("Service unavailable", 503)],
  ])("queues it once when online but the POST fails with %s", async (_label, error) => {
    apiFetchMock.mockRejectedValue(error);
    await expect(completeLessonUnit("mod-1", "1.2", { online: true })).resolves.toBe("queued");
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(addOfflineActionMock).toHaveBeenCalledTimes(1);
    expect(addOfflineActionMock).toHaveBeenCalledWith(queued);
  });

  it.each([400, 401, 403, 404, 422])("does not queue a %i refusal", async (status) => {
    const refusal = new ApiError("refused", status);
    apiFetchMock.mockRejectedValue(refusal);
    await expect(completeLessonUnit("mod-1", "1.2", { online: true })).rejects.toBe(refusal);
    expect(addOfflineActionMock).not.toHaveBeenCalled();
  });
});

describe("isTransientFailure", () => {
  it("is false for an aborted request and for ordinary errors", () => {
    expect(isTransientFailure(new DOMException("Aborted", "AbortError"))).toBe(false);
    expect(isTransientFailure(new Error("boom"))).toBe(false);
    expect(isTransientFailure(undefined)).toBe(false);
  });
});
