/**
 * "Mark complete" records the lesson unit once, however it is tapped, and
 * survives a flaky connection.
 *
 * On 2G the completion POST can die with `navigator.onLine` still true; it
 * used to be dropped for good. It is now queued for background sync, exactly
 * once, and the unit shows as completed — but a 4xx is not queued. As no
 * `online` event follows, the sync manager is asked to replay the queue on
 * its own.
 *
 * A POST that stalls (the link stays open, nothing comes back) is given up at
 * its deadline and queued the same way; meanwhile the button is busy.
 *
 * Story mode is no longer part of the lesson (a module has one story, opened
 * from the module page), so the button is the lesson's only completion path.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, getModuleDetailWithProgress } from "@/lib/api";
import { COMPLETION_TIMEOUT_MS } from "@/lib/learning/complete-lesson";
import { loadLesson } from "@/lib/offline/content-loader";
import { addOfflineAction, REPLAY_REQUESTED_EVENT } from "@/lib/offline/db";
import frMessages from "@/messages/fr.json";

import { LessonViewer } from "./lesson-viewer";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/analytics", () => ({ track: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    apiFetch: vi.fn(),
    getModuleDetailWithProgress: vi.fn(),
  };
});

vi.mock("@/lib/offline/content-loader", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/offline/content-loader")>();
  return { ...actual, loadLesson: vi.fn() };
});

vi.mock("@/lib/offline/db", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/offline/db")>();
  return { ...actual, addOfflineAction: vi.fn() };
});

// Audio, video and the lesson body are not under test.
vi.mock("./lesson-media-tabs", () => ({ LessonMediaTabs: () => null }));
vi.mock("./source-citations", () => ({ SourceCitations: () => null }));
// Pulls next-intl's navigation, which needs the Next runtime; not under test.
vi.mock("@/components/shared/subscription-required", () => ({
  SubscriptionRequired: () => null,
}));

const apiFetchMock = vi.mocked(apiFetch);
const loadLessonMock = vi.mocked(loadLesson);
const addOfflineActionMock = vi.mocked(addOfflineAction);

// A completion queued while online asks the sync manager for a replay; what
// the manager does with it is covered by lib/offline/sync-manager.test.ts.
const replayRequested = vi.fn();

const lesson = {
  id: "lesson-1",
  module_id: "mod-1",
  unit_id: "1.2",
  language: "fr",
  level: 1,
  country_context: "SN",
  content: {
    introduction: "Intro",
    concepts: [],
    aof_example: "",
    synthesis: "",
    key_points: [],
    sources_cited: [],
  },
  cached: true,
};

function renderViewer(onComplete = vi.fn()) {
  render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <LessonViewer moduleId="mod-1" unitId="1.2" language="fr" level={1} onComplete={onComplete} />
    </NextIntlClientProvider>,
  );
  return onComplete;
}

beforeEach(() => {
  apiFetchMock.mockReset();
  addOfflineActionMock.mockReset();
  addOfflineActionMock.mockResolvedValue(1);
  replayRequested.mockClear();
  window.addEventListener(REPLAY_REQUESTED_EVENT, replayRequested);
  vi.mocked(getModuleDetailWithProgress).mockResolvedValue(
    { units: [] } as unknown as Awaited<ReturnType<typeof getModuleDetailWithProgress>>,
  );
  loadLessonMock.mockResolvedValue({ data: lesson, source: "api" });
  window.localStorage.setItem(
    "user",
    JSON.stringify({ id: "u1", name: "Awa Diallo", preferred_language: "fr", country: "SN" }),
  );
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.useRealTimers();
  window.removeEventListener(REPLAY_REQUESTED_EVENT, replayRequested);
  window.localStorage.clear();
  vi.restoreAllMocks();
});

const completePosts = () =>
  apiFetchMock.mock.calls.filter(([path]) => path === "/api/v1/progress/complete-lesson");

const markComplete = () => screen.findByRole("button", { name: "Marquer comme Terminé" });

describe("LessonViewer — Mark complete", () => {
  it("records the unit once when the POST succeeds, even on a double tap", async () => {
    apiFetchMock.mockResolvedValue({ ok: true });
    const onComplete = renderViewer();
    const button = await markComplete();

    // Two taps in the same tick, before the busy state can disable the button.
    act(() => {
      button.click();
      button.click();
    });

    expect(await screen.findByRole("button", { name: "Terminé" })).toBeDisabled();
    expect(completePosts()).toHaveLength(1);
    expect(completePosts()[0][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ module_id: "mod-1", unit_id: "1.2" }),
    });
    expect(addOfflineActionMock).not.toHaveBeenCalled();
    expect(replayRequested).not.toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("starts as done when the unit is already completed", async () => {
    vi.mocked(getModuleDetailWithProgress).mockResolvedValue({
      units: [{ unit_number: "1.2", status: "completed" }],
    } as unknown as Awaited<ReturnType<typeof getModuleDetailWithProgress>>);
    renderViewer();

    expect(await screen.findByRole("button", { name: "Terminé" })).toBeDisabled();
    expect(completePosts()).toHaveLength(0);
  });

  it("queues it once when the POST dies on a flaky connection", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/v1/progress/complete-lesson") throw new TypeError("Failed to fetch");
      return { ok: true };
    });
    const onComplete = renderViewer();

    fireEvent.click(await markComplete());

    // Shown as completed, like the offline branch, and queued for sync once.
    expect(await screen.findByRole("button", { name: "Terminé" })).toBeDisabled();
    expect(completePosts()).toHaveLength(1);
    expect(addOfflineActionMock).toHaveBeenCalledTimes(1);
    expect(addOfflineActionMock).toHaveBeenCalledWith({
      actionType: "case_study_complete",
      payload: { module_id: "mod-1", unit_id: "1.2" },
    });
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    // No `online` event will come: the device never went offline.
    expect(replayRequested).toHaveBeenCalledTimes(1);
  });

  it("queues it on a server error too", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/v1/progress/complete-lesson") throw new ApiError("Bad gateway", 502);
      return { ok: true };
    });
    renderViewer();

    fireEvent.click(await markComplete());
    expect(await screen.findByRole("button", { name: "Terminé" })).toBeDisabled();
    expect(addOfflineActionMock).toHaveBeenCalledTimes(1);
  });

  it("does not queue a 4xx refusal and says so", async () => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === "/api/v1/progress/complete-lesson") throw new ApiError("Forbidden", 403);
      return { ok: true };
    });
    const onComplete = renderViewer();

    fireEvent.click(await markComplete());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Impossible de marquer cette leçon comme terminée.",
    );
    await act(async () => {});
    expect(addOfflineActionMock).not.toHaveBeenCalled();
    expect(replayRequested).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Marquer comme Terminé" })).toBeEnabled(),
    );
  });
});

describe("LessonViewer — Mark complete on a stalled connection", () => {
  it("is busy while the POST is in flight, then queues it once at the deadline", async () => {
    // The completion POST hangs, as on congested 2G; everything else answers.
    apiFetchMock.mockImplementation((path: string) =>
      path === "/api/v1/progress/complete-lesson"
        ? new Promise<never>(() => {})
        : Promise.resolve({ ok: true }),
    );
    const onComplete = renderViewer();
    const button = await screen.findByRole("button", { name: "Marquer comme Terminé" });
    expect(button).toHaveAttribute("aria-busy", "false");

    vi.useFakeTimers();
    fireEvent.click(button);

    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    // Another tap meanwhile starts nothing more.
    fireEvent.click(button);
    expect(completePosts()).toHaveLength(1);

    await act(() => vi.advanceTimersByTimeAsync(COMPLETION_TIMEOUT_MS - 1));
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(addOfflineActionMock).not.toHaveBeenCalled();
    expect(onComplete).not.toHaveBeenCalled();

    await act(() => vi.advanceTimersByTimeAsync(1));

    // Queued once and shown as completed, as on any other transient failure.
    const done = screen.getByRole("button", { name: "Terminé" });
    expect(done).toBeDisabled();
    expect(done).toHaveAttribute("aria-busy", "false");
    expect(completePosts()).toHaveLength(1);
    expect(addOfflineActionMock).toHaveBeenCalledTimes(1);
    expect(addOfflineActionMock).toHaveBeenCalledWith({
      actionType: "case_study_complete",
      payload: { module_id: "mod-1", unit_id: "1.2" },
    });
    expect(replayRequested).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("is ready again after a refusal", async () => {
    let refuse: (err: unknown) => void = () => {};
    apiFetchMock.mockImplementation((path: string) =>
      path === "/api/v1/progress/complete-lesson"
        ? new Promise<never>((_, reject) => {
            refuse = reject;
          })
        : Promise.resolve({ ok: true }),
    );
    renderViewer();
    const button = await screen.findByRole("button", { name: "Marquer comme Terminé" });

    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");

    await act(async () => refuse(new ApiError("Forbidden", 403)));

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(button).toHaveAttribute("aria-busy", "false");
    expect(button).toBeEnabled();
  });
});
