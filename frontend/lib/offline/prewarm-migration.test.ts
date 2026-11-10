/**
 * The v11 page prewarm (#2692): a page that will never come (a unit removed:
 * 404; storage full) must not keep the migration open, or every app start
 * and every `online` event would download every page of every downloaded
 * module again on a 2G phone.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PrewarmOutcome } from "./prewarm";

const state = vi.hoisted(() => ({
  outcomes: new Map<string, string>(),
  stored: new Set<string>(),
}));

vi.mock("@/lib/offline/db", async (importOriginal) => {
  const { REPLAY_REQUESTED_EVENT, requestOfflineReplay } =
    await importOriginal<typeof import("@/lib/offline/db")>();
  return {
    REPLAY_REQUESTED_EVENT,
    requestOfflineReplay,
    getPendingOfflineActions: vi.fn(async () => []),
    markOfflineActionSynced: vi.fn(),
    clearSyncedActions: vi.fn(),
    getOfflineModulesByStatus: vi.fn(async () => [{ moduleId: "mod-1" }]),
    getOfflineContentByModule: vi.fn(async () => [
      { unitId: "1.1", locale: "fr", contentType: "lesson" },
      { unitId: "1.6", locale: "fr", contentType: "lesson" },
      { unitId: "__module_mod-1__", locale: "fr", contentType: "story" },
    ]),
  };
});

vi.mock("./prewarm", () => ({
  prewarmPage: vi.fn(async (url: string): Promise<PrewarmOutcome> => {
    const outcome = (state.outcomes.get(url) ?? "cached") as PrewarmOutcome;
    if (outcome === "cached") state.stored.add(url);
    return outcome;
  }),
  isPagePrewarmed: vi.fn(async (url: string) => state.stored.has(url)),
  prewarmRetryable: (outcome: PrewarmOutcome) => outcome === "network_error" || outcome === "server_error",
}));

import { prewarmPage } from "./prewarm";
import {
  PREWARM_V11_BACKOFF_MS,
  PREWARM_V11_MAX_RUNS,
  PREWARM_V11_RUNS_KEY,
  SyncManager,
} from "./sync-manager";

const DONE = "offline_prewarm_v11_done";
const UNIT_GONE = "/fr/modules/mod-1/units/1.6";
const fetched = () => vi.mocked(prewarmPage).mock.calls.map(([url]) => url);
const manager = SyncManager.getInstance();

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-10T08:00:00Z"));
  state.outcomes.clear();
  state.stored.clear();
  vi.mocked(prewarmPage).mockClear();
  window.localStorage.clear();
  vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(true);
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("v11 page prewarm", () => {
  it("warms the unit, module and story pages of a downloaded module, then is done", async () => {
    await manager.runV11PrewarmMigration();
    expect(fetched()).toEqual([
      "/fr/modules/mod-1/units/1.1",
      UNIT_GONE,
      "/fr/modules/mod-1",
      "/fr/modules/mod-1/story",
    ]);
    expect(window.localStorage.getItem(DONE)).toBe("1");
  });

  it("is done even when a page is gone for good (404) or cannot be stored (storage full)", async () => {
    state.outcomes.set(UNIT_GONE, "gone");
    state.outcomes.set("/fr/modules/mod-1/story", "store_error");
    await manager.runV11PrewarmMigration();
    expect(window.localStorage.getItem(DONE)).toBe("1");

    // Nothing more is downloaded on the next start.
    vi.mocked(prewarmPage).mockClear();
    await manager.runV11PrewarmMigration();
    expect(fetched()).toEqual([]);
  });

  it("tries again later when the link dropped, without fetching what it stored", async () => {
    state.outcomes.set(UNIT_GONE, "network_error");
    await manager.runV11PrewarmMigration();
    expect(window.localStorage.getItem(DONE)).toBeNull();
    expect(window.localStorage.getItem(PREWARM_V11_RUNS_KEY)).toBe("1");

    // Too soon: the wait between runs is kept across starts.
    vi.mocked(prewarmPage).mockClear();
    await manager.runV11PrewarmMigration();
    expect(fetched()).toEqual([]);

    // Later, the link is back: only the page that failed is fetched.
    vi.setSystemTime(Date.now() + PREWARM_V11_BACKOFF_MS + 1);
    state.outcomes.delete(UNIT_GONE);
    await manager.runV11PrewarmMigration();
    expect(fetched()).toEqual([UNIT_GONE]);
    expect(window.localStorage.getItem(DONE)).toBe("1");
  });

  it("gives up after a few runs on a page that never comes", async () => {
    state.outcomes.set(UNIT_GONE, "server_error");
    for (let run = 0; run < PREWARM_V11_MAX_RUNS + 2; run += 1) {
      await manager.runV11PrewarmMigration();
      vi.setSystemTime(Date.now() + 24 * 60 * 60 * 1000);
    }
    expect(fetched().filter((url) => url === UNIT_GONE)).toHaveLength(PREWARM_V11_MAX_RUNS);
    expect(window.localStorage.getItem(DONE)).toBe("1");
  });

  it("runs once when it is asked twice at the same time", async () => {
    await Promise.all([manager.runV11PrewarmMigration(), manager.runV11PrewarmMigration()]);
    expect(fetched()).toHaveLength(4);
  });

  it("waits for the link to be up", async () => {
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    await manager.runV11PrewarmMigration();
    expect(fetched()).toEqual([]);
    expect(window.localStorage.getItem(DONE)).toBeNull();
  });
});
