/**
 * Completing a lesson unit on a flaky connection: `navigator.onLine` says
 * online, the POST dies anyway. The completion must be queued for background
 * sync, as it is offline, not dropped. A 4xx is a real refusal and is not.
 *
 * A completion queued while the device still looks online gets no `online`
 * event, so it must not wait for one: the real sync manager, started as the
 * app layout starts it, replays it on a short backoff, against an in-memory
 * stand-in for the IndexedDB queue.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api";
import { addOfflineAction, type OfflineAction } from "@/lib/offline/db";
import { REPLAY_DELAYS_MS, SyncManager } from "@/lib/offline/sync-manager";

import { completeLessonUnit, isTransientFailure } from "./complete-lesson";

const queue = vi.hoisted(() => ({ actions: [] as OfflineAction[], nextId: 1 }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock("@/lib/offline/db", async (importOriginal) => {
  const { REPLAY_REQUESTED_EVENT, requestOfflineReplay } =
    await importOriginal<typeof import("@/lib/offline/db")>();
  return {
    // The real replay request: a window event the started manager listens for.
    REPLAY_REQUESTED_EVENT,
    requestOfflineReplay,
    addOfflineAction: vi.fn(
      async (action: Omit<OfflineAction, "id" | "createdAt" | "synced">) => {
        const id = queue.nextId++;
        queue.actions.push({ ...action, id, createdAt: Date.now(), synced: 0 });
        return id;
      },
    ),
    getPendingOfflineActions: vi.fn(async () => queue.actions.filter((a) => a.synced === 0)),
    markOfflineActionSynced: vi.fn(async (id: number) => {
      const action = queue.actions.find((a) => a.id === id);
      if (action) action.synced = 1;
    }),
    clearSyncedActions: vi.fn(async () => {
      queue.actions = queue.actions.filter((a) => a.synced === 0);
    }),
    getOfflineModulesByStatus: vi.fn(async () => []),
    getOfflineContentByModule: vi.fn(async () => []),
  };
});

vi.mock("@/lib/offline/download-manager", () => ({ prewarmPage: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);
const addOfflineActionMock = vi.mocked(addOfflineAction);

const queued = {
  actionType: "case_study_complete",
  payload: { module_id: "mod-1", unit_id: "1.2" },
};

const completePosts = () =>
  apiFetchMock.mock.calls.filter(([path]) => path === "/api/v1/progress/complete-lesson");

beforeEach(async () => {
  vi.useFakeTimers();
  queue.actions = [];
  queue.nextId = 1;
  apiFetchMock.mockReset();
  addOfflineActionMock.mockClear();
  vi.spyOn(console, "warn").mockImplementation(() => {});
  // As the app layout does (useSyncStatus); its start-up replay finds nothing.
  SyncManager.getInstance().start();
  await vi.runAllTimersAsync();
});

afterEach(() => {
  SyncManager.getInstance().stop();
  vi.useRealTimers();
  vi.restoreAllMocks();
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
    expect(vi.getTimerCount()).toBe(0);
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

describe("completeLessonUnit — replaying a completion queued while online", () => {
  it("sends it again on its own, with no `online` event, once the link recovers", async () => {
    // The first POST dies on 2G; the link is back by the replay.
    apiFetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    apiFetchMock.mockResolvedValue({ ok: true });

    await expect(completeLessonUnit("mod-1", "1.2", { online: true })).resolves.toBe("queued");
    expect(completePosts()).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(REPLAY_DELAYS_MS[0]);

    expect(completePosts()).toHaveLength(2);
    expect(completePosts()[1]).toEqual([
      "/api/v1/progress/complete-lesson",
      { method: "POST", body: JSON.stringify({ module_id: "mod-1", unit_id: "1.2" }) },
    ]);
    expect(queue.actions).toEqual([]);
    // Drained: nothing more is scheduled.
    await vi.runAllTimersAsync();
    expect(completePosts()).toHaveLength(2);
  });

  it("keeps trying on the backoff while the link stays bad, then stops", async () => {
    apiFetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await completeLessonUnit("mod-1", "1.2", { online: true });
    await vi.runAllTimersAsync();

    // 1 first POST + every scheduled replay (each tries the action 3 times).
    expect(completePosts()).toHaveLength(1 + REPLAY_DELAYS_MS.length * 3);
    expect(vi.getTimerCount()).toBe(0);
    // Still queued for the next `online` event or app start.
    expect(queue.actions).toHaveLength(1);
  });

  it("lets a second failure join the replay already scheduled", async () => {
    apiFetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    apiFetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    apiFetchMock.mockResolvedValue({ ok: true });

    await completeLessonUnit("mod-1", "1.2", { online: true });
    await completeLessonUnit("mod-1", "1.3", { online: true });
    expect(vi.getTimerCount()).toBe(1);

    await vi.advanceTimersByTimeAsync(REPLAY_DELAYS_MS[0]);

    // One replay sends both queued completions.
    expect(completePosts()).toHaveLength(4);
    expect(queue.actions).toEqual([]);
  });

  it("leaves an offline completion to the `online` event", async () => {
    apiFetchMock.mockResolvedValue({ ok: true });

    await completeLessonUnit("mod-1", "1.2", { online: false });
    await vi.advanceTimersByTimeAsync(REPLAY_DELAYS_MS[0]);

    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(queue.actions).toHaveLength(1);
  });

  it("schedules nothing for a 4xx refusal", async () => {
    apiFetchMock.mockRejectedValue(new ApiError("Forbidden", 403));

    await expect(completeLessonUnit("mod-1", "1.2", { online: true })).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("isTransientFailure", () => {
  it("is false for an aborted request and for ordinary errors", () => {
    expect(isTransientFailure(new DOMException("Aborted", "AbortError"))).toBe(false);
    expect(isTransientFailure(new Error("boom"))).toBe(false);
    expect(isTransientFailure(undefined)).toBe(false);
  });
});
