import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// No session: apiFetch proceeds without a token instead of attempting a refresh.
vi.mock("../auth", () => ({
  authClient: {
    getValidToken: vi.fn(async () => {
      throw new Error("no token");
    }),
  },
}));

vi.mock("./db", () => ({
  addOfflineAction: vi.fn(async () => 1),
  getPendingOfflineActions: vi.fn(async () => []),
  markOfflineActionSynced: vi.fn(async () => undefined),
  clearSyncedActions: vi.fn(async () => undefined),
  getOfflineModulesByStatus: vi.fn(async () => []),
  getOfflineContentByModule: vi.fn(async () => []),
  upsertOfflineContent: vi.fn(async () => undefined),
}));

vi.mock("./download-manager", () => ({ prewarmPage: vi.fn(async () => undefined) }));

import { ApiError, isQuizChangedError, type Quiz } from "../api";
import { quizAttemptStorageKey } from "../quiz-state-persistence";
import * as db from "./db";
import { scoreQuizOffline } from "./offline-quiz-scorer";
import { SyncManager, buildQueuedQuizAttemptBody, type SyncStatus } from "./sync-manager";

function jsonResponse(status: number, body: unknown) {
  return { ok: status < 400, status, json: async () => body };
}

function quiz(overrides: Partial<Quiz> = {}): Quiz {
  return {
    id: "quiz-1",
    module_id: "module-1",
    unit_id: "1.2",
    language: "fr",
    level: 1,
    country_context: "SN",
    generated_at: "2026-01-01T00:00:00",
    cached: true,
    content: {
      title: "Quiz",
      description: "",
      passing_score: 80,
      questions: [
        {
          id: "q1",
          question: "?",
          options: ["a", "b", "c", "d"],
          correct_answer: 1,
          explanation: "",
          sources_cited: [],
          difficulty: "easy",
        },
      ],
    },
    ...overrides,
  };
}

describe("isQuizChangedError", () => {
  it("recognises the 409 quiz_changed refusal", () => {
    expect(isQuizChangedError(new ApiError("changed", 409, undefined, { error: "quiz_changed" }))).toBe(true);
    expect(isQuizChangedError(new ApiError("changed", 409, "quiz_changed"))).toBe(true);
  });

  it("ignores other conflicts and statuses", () => {
    expect(isQuizChangedError(new ApiError("dup", 409, undefined, { error: "duplicate" }))).toBe(false);
    expect(isQuizChangedError(new ApiError("bad", 400, undefined, { error: "quiz_changed" }))).toBe(false);
    expect(isQuizChangedError(new Error("network"))).toBe(false);
    expect(isQuizChangedError(null)).toBe(false);
  });
});

describe("quizAttemptStorageKey", () => {
  it("keeps the pre-revision key for revision 1 and unrevisioned payloads", () => {
    expect(quizAttemptStorageKey("quiz-state", { id: "x" })).toBe("quiz-state:v1:x");
    expect(quizAttemptStorageKey("quiz-state", { id: "x", content_revision: 1 })).toBe("quiz-state:v1:x");
  });

  it("gives a regenerated quiz a fresh key, so old answers are not restored onto it", () => {
    const before = quizAttemptStorageKey("summative-state", { id: "x", content_revision: 1 });
    const after = quizAttemptStorageKey("summative-state", { id: "x", content_revision: 2 });
    expect(after).toBe("summative-state:v1:x:r2");
    expect(after).not.toBe(before);
  });
});

describe("offline quiz answers are pinned to the revision served", () => {
  beforeEach(() => {
    vi.mocked(db.addOfflineAction).mockClear();
  });

  it("queues content_revision with the answers", async () => {
    await scoreQuizOffline(quiz({ content_revision: 3 }), { q1: 1 }, 42);
    const queued = vi.mocked(db.addOfflineAction).mock.calls[0][0];
    expect(queued.actionType).toBe("quiz_answer");
    expect(queued.payload).toMatchObject({ quiz_id: "quiz-1", content_revision: 3, answers: { q1: 1 } });
  });

  it("builds the attempt body the endpoint accepts", () => {
    expect(
      buildQueuedQuizAttemptBody({
        quiz_id: "quiz-1",
        answers: { q1: 1, q2: 0 },
        total_time_seconds: 42,
        content_revision: 3,
      }),
    ).toEqual({
      quiz_id: "quiz-1",
      answers: [
        { question_id: "q1", selected_option: 1, time_taken_seconds: 0 },
        { question_id: "q2", selected_option: 0, time_taken_seconds: 0 },
      ],
      total_time_seconds: 42,
      content_revision: 3,
    });
  });

  it("sends no revision for entries queued before it existed", () => {
    const body = buildQueuedQuizAttemptBody({ quiz_id: "quiz-1", answers: { q1: 1 }, total_time_seconds: 5 });
    expect(body).not.toHaveProperty("content_revision");
  });

  it("sends an entry queued before revisions existed with neither a revision nor an answer time", () => {
    // The server grades it only if the quiz never changed, else 409 quiz_changed:
    // when it was answered says nothing about when its questions were obtained.
    const body = buildQueuedQuizAttemptBody({
      quiz_id: "quiz-1",
      answers: { q1: 1 },
      total_time_seconds: 5,
      offline_scored_at: "2026-03-04T05:06:07.000Z",
    });
    expect(body).toEqual({
      quiz_id: "quiz-1",
      answers: [{ question_id: "q1", selected_option: 1, time_taken_seconds: 0 }],
      total_time_seconds: 5,
    });
    expect(body).not.toHaveProperty("answered_at");
  });
});

describe("SyncManager quiz_answer sync", () => {
  const action = {
    id: 7,
    actionType: "quiz_answer" as const,
    payload: {
      quiz_id: "quiz-1",
      module_id: "module-1",
      unit_id: "1.2",
      answers: { q1: 1 },
      total_time_seconds: 42,
      content_revision: 1,
    },
    createdAt: 0,
    synced: 0,
  };

  let statuses: SyncStatus[];
  let unsubscribe: () => void;

  beforeEach(() => {
    vi.mocked(db.getPendingOfflineActions).mockResolvedValue([action]);
    vi.mocked(db.markOfflineActionSynced).mockClear();
    vi.mocked(db.upsertOfflineContent).mockClear();
    statuses = [];
    unsubscribe = SyncManager.getInstance().onStatusChange((s) => statuses.push(s));
  });

  afterEach(() => {
    unsubscribe();
    vi.unstubAllGlobals();
  });

  it("sends the queued revision with the attempt", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(201, {}));
    vi.stubGlobal("fetch", fetchMock);

    const result = await SyncManager.getInstance().syncNow();

    expect(result).toEqual({ synced: 1, failed: 0 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/v1/quiz/attempt");
    expect(JSON.parse(init.body)).toMatchObject({
      quiz_id: "quiz-1",
      content_revision: 1,
      answers: [{ question_id: "q1", selected_option: 1, time_taken_seconds: 0 }],
    });
    expect(db.markOfflineActionSynced).toHaveBeenCalledWith(7);
  });

  it("drops a legacy entry refused with 409, refreshes its quiz copy and says so", async () => {
    const legacy: Partial<typeof action.payload> & { offline_scored_at?: string } = {
      ...action.payload,
      offline_scored_at: "2026-03-04T05:06:07.000Z",
    };
    delete legacy.content_revision;
    vi.mocked(db.getPendingOfflineActions).mockResolvedValue([
      { ...action, payload: legacy, createdAt: Date.UTC(2026, 1, 3, 4, 5, 6) },
    ]);
    const current = quiz({ content_revision: 2 });
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/api/v1/quiz/attempt")
        ? jsonResponse(409, { detail: { error: "quiz_changed", message: "changed" } })
        : jsonResponse(200, current),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await SyncManager.getInstance().syncNow();

    const attemptCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/quiz/attempt"));
    expect(attemptCalls).toHaveLength(1);
    const body = JSON.parse((attemptCalls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(body).not.toHaveProperty("content_revision");
    expect(body).not.toHaveProperty("answered_at");
    expect(result).toEqual({ synced: 0, failed: 0 });
    expect(db.markOfflineActionSynced).toHaveBeenCalledWith(7);
    expect(db.upsertOfflineContent).toHaveBeenCalledWith(
      expect.objectContaining({ moduleId: "module-1", unitId: "1.2", contentType: "quiz", content: current }),
    );
    expect(statuses.at(-1)).toEqual({ state: "complete", synced: 0, quizChanged: 1 });
  });

  it("drops answers to a changed quiz, refreshes the offline copy and says so", async () => {
    const current = quiz({ content_revision: 2 });
    const fetchMock = vi.fn(async (url: string) =>
      String(url).endsWith("/api/v1/quiz/attempt")
        ? jsonResponse(409, { detail: { error: "quiz_changed", message: "changed" } })
        : jsonResponse(200, current),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await SyncManager.getInstance().syncNow();

    // One attempt only: retrying cannot make the old revision gradeable.
    const attemptCalls = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/quiz/attempt"));
    expect(attemptCalls).toHaveLength(1);
    expect(result).toEqual({ synced: 0, failed: 0 });
    expect(db.markOfflineActionSynced).toHaveBeenCalledWith(7);
    expect(db.upsertOfflineContent).toHaveBeenCalledWith(
      expect.objectContaining({ moduleId: "module-1", unitId: "1.2", contentType: "quiz", locale: "fr", content: current }),
    );
    expect(statuses.at(-1)).toEqual({ state: "complete", synced: 0, quizChanged: 1 });
  });
});
