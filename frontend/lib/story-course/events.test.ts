/**
 * Anonymised story events (#2711): the learner's opt-out is honoured, an event
 * carries no free text, and one that cannot be sent is queued for the sync
 * manager instead of being lost.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api";
import { addOfflineAction } from "@/lib/offline/db";

import { cleanStoryEvent, reportStoryEvent, type StoryEvent } from "./events";

vi.mock("@/lib/api", () => ({ apiFetch: vi.fn() }));
vi.mock("@/lib/offline/db", () => ({
  addOfflineAction: vi.fn(async () => 1),
  requestOfflineReplay: vi.fn(),
}));

const post = vi.mocked(apiFetch);
const queued = vi.mocked(addOfflineAction);

const bet: StoryEvent = {
  event: "story_prediction",
  story: "module-abc-fr",
  chapter: "u1_1",
  question: "u1_1-p1",
  lang: "fr",
  matched: true,
};

function online(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

beforeEach(() => {
  post.mockReset();
  queued.mockClear();
  online(true);
});

afterEach(() => {
  window.localStorage.clear();
});

describe("reportStoryEvent", () => {
  it("posts the event, and nothing else, to the story-events route", async () => {
    post.mockResolvedValue({});
    expect(await reportStoryEvent(bet)).toBe("sent");
    expect(post).toHaveBeenCalledWith("/api/v1/analytics/story-events", {
      method: "POST",
      body: JSON.stringify({ events: [bet] }),
    });
  });

  it("sends and queues nothing for a learner who opted out", async () => {
    window.localStorage.setItem("analytics_opt_out", "1");
    expect(await reportStoryEvent(bet)).toBe("skipped");
    expect(post).not.toHaveBeenCalled();
    expect(queued).not.toHaveBeenCalled();
  });

  it("queues the event when offline, for the sync manager to replay", async () => {
    online(false);
    expect(await reportStoryEvent(bet)).toBe("queued");
    expect(post).not.toHaveBeenCalled();
    expect(queued).toHaveBeenCalledWith({ actionType: "story_events", payload: { events: [bet] } });
  });

  it("queues it when the network fails, and drops it when the server refuses it", async () => {
    post.mockRejectedValueOnce(new Error("socket hang up"));
    expect(await reportStoryEvent(bet)).toBe("queued");
    post.mockRejectedValueOnce(Object.assign(new Error("nope"), { status: 422 }));
    expect(await reportStoryEvent(bet)).toBe("skipped");
    expect(queued).toHaveBeenCalledTimes(1);
  });

  it("never lets measuring break a story", async () => {
    online(false);
    queued.mockRejectedValueOnce(new Error("IndexedDB is gone"));
    await expect(reportStoryEvent(bet)).resolves.toBe("skipped");
  });
});

describe("cleanStoryEvent", () => {
  it("refuses an id that is not an identifier (a name, a sentence)", () => {
    expect(cleanStoryEvent(bet)).toEqual(bet);
    expect(cleanStoryEvent({ ...bet, story: "Awa's story" })).toBeNull();
    expect(cleanStoryEvent({ ...bet, question: "q 1" })).toBeNull();
    expect(cleanStoryEvent({ ...bet, chapter: undefined })).not.toBeNull();
  });
});
