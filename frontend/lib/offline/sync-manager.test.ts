/**
 * The sync manager used to replay the offline queue only on a window `online`
 * event. An action queued while `navigator.onLine` stayed true (a POST that
 * died on 2G) never sees one, so it could sit in IndexedDB indefinitely. The
 * queue is now also replayed when the app opens online, and on a backoff
 * after scheduleSync().
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api";
import {
  getPendingOfflineActions,
  requestOfflineReplay,
  type OfflineAction,
} from "@/lib/offline/db";

import { REPLAY_DELAYS_MS, SyncManager } from "./sync-manager";

const queue = vi.hoisted(() => ({ actions: [] as OfflineAction[] }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

vi.mock("@/lib/offline/db", async (importOriginal) => {
  const { REPLAY_REQUESTED_EVENT, requestOfflineReplay } =
    await importOriginal<typeof import("@/lib/offline/db")>();
  return {
    REPLAY_REQUESTED_EVENT,
    requestOfflineReplay,
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

vi.mock("./prewarm", () => ({
  prewarmPage: vi.fn(async () => "cached"),
  isPagePrewarmed: vi.fn(async () => false),
  prewarmRetryable: () => false,
}));

const apiFetchMock = vi.mocked(apiFetch);
const manager = SyncManager.getInstance();

const completePosts = () =>
  apiFetchMock.mock.calls.filter(([path]) => path === "/api/v1/progress/complete-lesson");

/** A completion queued in an earlier session, left pending. */
function queueCompletion() {
  queue.actions = [
    {
      id: 1,
      actionType: "case_study_complete",
      payload: { module_id: "mod-1", unit_id: "1.2" },
      createdAt: 0,
      synced: 0,
    },
  ];
}

function setOnline(online: boolean) {
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(online);
}

beforeEach(() => {
  vi.useFakeTimers();
  queue.actions = [];
  apiFetchMock.mockReset();
  apiFetchMock.mockResolvedValue({ ok: true });
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

afterEach(() => {
  manager.stop();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("SyncManager.start", () => {
  it("replays a queue left from an earlier session when the app opens online", async () => {
    setOnline(true);
    queueCompletion();

    manager.start();
    await vi.runAllTimersAsync();

    expect(completePosts()).toHaveLength(1);
    expect(queue.actions).toEqual([]);
  });

  it("leaves the queue to the `online` event when the app opens offline", async () => {
    setOnline(false);
    queueCompletion();

    manager.start();
    await vi.runAllTimersAsync();
    expect(apiFetchMock).not.toHaveBeenCalled();

    setOnline(true);
    window.dispatchEvent(new Event("online"));
    await vi.runAllTimersAsync();
    expect(completePosts()).toHaveLength(1);
    expect(queue.actions).toEqual([]);
  });
});

describe("SyncManager — replay requests", () => {
  it("schedules a replay when asked, once started, and stops listening on stop()", async () => {
    setOnline(false);
    manager.start();
    setOnline(true);
    queueCompletion();

    requestOfflineReplay();
    await vi.advanceTimersByTimeAsync(REPLAY_DELAYS_MS[0]);
    expect(completePosts()).toHaveLength(1);

    manager.stop();
    queueCompletion();
    requestOfflineReplay();
    await vi.runAllTimersAsync();
    expect(completePosts()).toHaveLength(1);
  });
});

describe("SyncManager.scheduleSync", () => {
  it("replays the queue after the first delay, without an `online` event", async () => {
    setOnline(true);
    queueCompletion();

    manager.scheduleSync();
    await vi.advanceTimersByTimeAsync(REPLAY_DELAYS_MS[0] - 1);
    expect(apiFetchMock).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(completePosts()).toHaveLength(1);
    expect(queue.actions).toEqual([]);
  });

  it("skips a replay that comes due while offline", async () => {
    setOnline(false);
    queueCompletion();

    manager.scheduleSync();
    await vi.runAllTimersAsync();

    expect(apiFetchMock).not.toHaveBeenCalled();
    expect(queue.actions).toHaveLength(1);
  });

  it("can be cancelled", async () => {
    setOnline(true);
    queueCompletion();

    manager.scheduleSync();
    manager.cancelScheduledSync();
    await vi.runAllTimersAsync();

    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});

describe("SyncManager.syncNow", () => {
  it("is not wedged shut by an IndexedDB error", async () => {
    queueCompletion();
    vi.mocked(getPendingOfflineActions).mockRejectedValueOnce(new Error("IDB closed"));

    await expect(manager.syncNow()).rejects.toThrow("IDB closed");
    await expect(manager.syncNow()).resolves.toEqual({ synced: 1, failed: 0 });
    expect(queue.actions).toEqual([]);
  });
});
