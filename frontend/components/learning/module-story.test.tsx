/**
 * The module story panel (contract C-5).
 *
 * What matters to a learner on 2G: a story still being written is polled
 * gently, with a "you can leave" hint and a cap; the paywall, the feature
 * switch and a missing story each say so plainly; the story opens at the
 * first chapter not finished, holds one chapter at a time, and finishing a
 * lesson chapter completes that lesson once — never a quiz or a case study.
 */

import { act, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, getModuleDetailWithProgress } from "@/lib/api";
import { completeLessonUnit } from "@/lib/learning/complete-lesson";
import { OfflineContentNotAvailable } from "@/lib/offline/content-loader";
import { loadModuleStory } from "@/lib/story-course/load";
import { storyProgressKey } from "@/lib/story-course/progress";
import type { ChapterCovers, StoryCourse } from "@/lib/story-course/types";
import frMessages from "@/messages/fr.json";

import {
  LEAVE_HINT_MS,
  ModuleStory,
  POLL_INTERVAL_MS,
  POLL_MAX_CONSECUTIVE_ERRORS,
  POLL_TIMEOUT_MS,
} from "./module-story";

// The story player draws a cartoon stage per chapter: give the first render
// and long click-throughs headroom on a busy CI runner.
configure({ asyncUtilTimeout: 4000 });
vi.setConfig({ testTimeout: 20_000 });

vi.mock("@/lib/story-course/load", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/story-course/load")>();
  return { ...actual, loadModuleStory: vi.fn() };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn(), getModuleDetailWithProgress: vi.fn() };
});

vi.mock("@/lib/learning/complete-lesson", () => ({ completeLessonUnit: vi.fn() }));

// The next-intl Link needs the Next runtime; a plain anchor is enough here.
vi.mock("@/i18n/routing", () => ({
  Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

const loadMock = vi.mocked(loadModuleStory);
const apiFetchMock = vi.mocked(apiFetch);
const detailMock = vi.mocked(getModuleDetailWithProgress);
const completeMock = vi.mocked(completeLessonUnit);

const MODULE_ID = "6f1c2d3e-4b5a-6978-8a9b-0c1d2e3f4a5b";
const STORY_ID = "module-6f1c2d3e4b5a69788a9b0c1d2e3f4a5b-fr";
const USER_ID = "u1";

function covers(
  unit: string,
  role: ChapterCovers["role"],
  status: ChapterCovers["status"],
  maxPoints = 0,
): ChapterCovers {
  return {
    module_unit_id: `unit-${unit}`,
    unit_number: unit,
    unit_type: role === "lesson" ? "lesson" : role === "quiz_checkpoint" ? "quiz" : "case-study",
    role,
    status,
    completes_unit: role === "lesson" && status === "ready",
    max_points: maxPoints,
  };
}

/**
 * A cached module story, name-free: lesson 1.1 (a question, 2 points),
 * lesson 1.2 (two lines), the quiz 1.3 checkpoint and the case 1.4 checkpoint.
 */
function moduleStory(): StoryCourse {
  return {
    format: "story-course/1",
    id: STORY_ID,
    course: "Santé publique",
    unit: "Module 1 · Hygiène",
    week: 1,
    title: { en: "{child} and hygiene", fr: "{child} et l'hygiène" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "{child}" },
    objectives: [{ id: "u1_1-o1", en: "Wash hands", fr: "Se laver les mains" }],
    cast: [
      { id: "margo", name: "Margo", kind: "ai_tutor", art: "margo" },
      { id: "mentor", name: "Dr Kaboré", kind: "adult", art: "mr_kabore" },
    ],
    chapters: [
      {
        id: "ch1",
        title: { en: "Clean hands", fr: "Des mains propres" },
        covers: covers("1.1", "lesson", "ready", 2),
        scenes: [
          {
            id: "s1",
            place: "clinic",
            steps: [
              {
                type: "narrate",
                en: "{child} walks into the health centre.",
                fr: "{child} entre dans le centre de santé.",
              },
              { type: "ask", ref: "u1_1-q1" },
            ],
          },
        ],
      },
      {
        id: "ch2",
        title: { en: "Clean water", fr: "De l'eau propre" },
        covers: covers("1.2", "lesson", "ready"),
        scenes: [
          {
            id: "s2",
            place: "village",
            steps: [
              { type: "narrate", en: "{child} goes to the well.", fr: "{child} va au puits." },
              { type: "narrate", en: "The water is clear.", fr: "L'eau est claire." },
            ],
          },
        ],
      },
      {
        id: "ch3",
        title: { en: "Quiz time", fr: "L'heure du quiz" },
        covers: covers("1.3", "quiz_checkpoint", "checkpoint"),
        scenes: [
          {
            id: "s3",
            place: "classroom",
            steps: [
              { type: "narrate", en: "{child}, the quiz awaits.", fr: "{child}, le quiz t'attend." },
            ],
          },
        ],
      },
      {
        id: "ch4",
        title: { en: "A case at the clinic", fr: "Un cas au centre" },
        covers: covers("1.4", "case_checkpoint", "checkpoint"),
        scenes: [
          {
            id: "s4",
            place: "clinic",
            steps: [
              { type: "narrate", en: "{child}, a case awaits.", fr: "{child}, un cas t'attend." },
            ],
          },
        ],
      },
    ],
    questions: [
      {
        id: "u1_1-q1",
        type: "choice",
        objective: "u1_1-o1",
        prompt: { en: "When do you wash your hands?", fr: "Quand se lave-t-on les mains ?" },
        answer: "a",
        choices: [
          { id: "a", en: "Before touching a patient", fr: "Avant de toucher un patient" },
          {
            id: "b",
            en: "Only when they look dirty",
            fr: "Seulement si elles semblent sales",
            misconception: "u1_1-m1",
          },
        ],
      },
    ],
    rewards: { unit: { en: "points", fr: "points" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
    module_story: {
      module_id: MODULE_ID,
      module_number: 1,
      assembler: 1,
      revision: "0123456789abcdef",
    },
  };
}

function moduleDetail(completed: string[] = []) {
  return {
    id: MODULE_ID,
    module_number: 1,
    level: 1,
    title_fr: "Hygiène",
    title_en: "Hygiene",
    estimated_hours: 2,
    prereq_modules: [],
    status: "in_progress" as const,
    completion_pct: 0,
    quiz_score_avg: null,
    time_spent_minutes: 0,
    last_accessed: null,
    units: ["1.1", "1.2", "1.3", "1.4"].map((unit, index) => ({
      id: `unit-${unit}`,
      unit_number: unit,
      title_fr: unit,
      title_en: unit,
      estimated_minutes: 10,
      order_index: index,
      status: completed.includes(unit) ? ("completed" as const) : ("pending" as const),
    })),
  };
}

function renderPanel() {
  return render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <ModuleStory moduleId={MODULE_ID} language="fr" />
    </NextIntlClientProvider>,
  );
}

const GENERATING = "Écriture de l'histoire de ce module…";
const LEAVE_HINT = "Tu peux quitter cette page et revenir plus tard : l'écriture de l'histoire continue.";
const CH1_LINE = "Aminata entre dans le centre de santé.";
const CH2_LINE = "Aminata va au puits.";

beforeEach(() => {
  loadMock.mockReset();
  apiFetchMock.mockReset();
  detailMock.mockReset();
  detailMock.mockResolvedValue(moduleDetail());
  completeMock.mockReset();
  completeMock.mockResolvedValue("recorded");
  window.localStorage.setItem(
    "user",
    JSON.stringify({
      id: USER_ID,
      email: null,
      name: "Dr Aminata Diallo",
      preferred_language: "fr",
      current_level: 1,
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

/** Fake timers that still let promises and user-event run. */
function installFakeTimers() {
  vi.useFakeTimers({ shouldAdvanceTime: false });
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("ModuleStory — being written", () => {
  it("polls the content status every 5 s on a 202, then plays the story", async () => {
    installFakeTimers();
    loadMock
      .mockResolvedValueOnce({ status: "generating", task_id: "task-9" })
      .mockResolvedValueOnce(moduleStory());
    apiFetchMock
      .mockResolvedValueOnce({ status: "pending" })
      .mockResolvedValueOnce({ status: "complete", content_id: "story-1" });
    renderPanel();

    await advance(0);
    expect(screen.getByText(GENERATING)).toBeInTheDocument();
    expect(loadMock).toHaveBeenCalledWith(MODULE_ID, "fr");

    await advance(POLL_INTERVAL_MS - 1);
    expect(apiFetchMock).not.toHaveBeenCalled();
    await advance(1);
    expect(apiFetchMock).toHaveBeenLastCalledWith("/api/v1/content/status/task-9");
    expect(screen.getByText(GENERATING)).toBeInTheDocument();

    // Done: the story is read again through the loader (and so stored offline).
    await advance(POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(loadMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(CH1_LINE)).toBeInTheDocument();
  });

  it("says the learner can leave only after 30 s", async () => {
    installFakeTimers();
    loadMock.mockResolvedValue({ status: "generating", task_id: "task-1" });
    apiFetchMock.mockResolvedValue({ status: "generating" });
    renderPanel();

    await advance(0);
    expect(screen.getByText(GENERATING)).toBeInTheDocument();
    await advance(LEAVE_HINT_MS - POLL_INTERVAL_MS);
    expect(screen.queryByText(LEAVE_HINT)).not.toBeInTheDocument();
    await advance(POLL_INTERVAL_MS);
    expect(screen.getByText(LEAVE_HINT)).toBeInTheDocument();
    expect(screen.getByText(GENERATING)).toBeInTheDocument();
  });

  it("stops polling after 15 min and says to come back later", async () => {
    installFakeTimers();
    loadMock.mockResolvedValue({ status: "generating", task_id: "task-1" });
    apiFetchMock.mockResolvedValue({ status: "pending" });
    renderPanel();

    await advance(0);
    await advance(POLL_TIMEOUT_MS + POLL_INTERVAL_MS);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "L'histoire prend plus de temps que d'habitude. Reviens plus tard : l'écriture continue.",
    );
    const polls = apiFetchMock.mock.calls.length;
    expect(polls).toBeLessThanOrEqual(POLL_TIMEOUT_MS / POLL_INTERVAL_MS);
    await advance(10 * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(polls);
    expect(screen.getByRole("button", { name: /Réessayer/ })).toBeInTheDocument();
  });

  it.each([
    ["a dropped request", new TypeError("Failed to fetch")],
    ["a 502 during a deploy", new ApiError("Bad gateway", 502)],
    ["a 429", new ApiError("Too many requests", 429)],
  ])("keeps polling through %s: the task is still writing", async (_label, error) => {
    installFakeTimers();
    loadMock
      .mockResolvedValueOnce({ status: "generating", task_id: "task-1" })
      .mockResolvedValueOnce(moduleStory());
    apiFetchMock
      .mockResolvedValueOnce({ status: "generating" })
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({ status: "generating" })
      .mockResolvedValueOnce({ status: "complete", content_id: "story-1" });
    renderPanel();

    await advance(0);
    await advance(2 * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByText(GENERATING)).toBeInTheDocument();

    await advance(2 * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(4);
    expect(screen.getByText(CH1_LINE)).toBeInTheDocument();
  });

  it("gives up after a run of failed polls, and on a refusal at once", async () => {
    installFakeTimers();
    loadMock.mockResolvedValue({ status: "generating", task_id: "task-1" });
    apiFetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderPanel();

    await advance(0);
    await advance(POLL_MAX_CONSECUTIVE_ERRORS * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(POLL_MAX_CONSECUTIVE_ERRORS);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "L'histoire n'a pas pu être préparée. Réessaie : les chapitres déjà écrits sont conservés.",
    );
    await advance(10 * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(POLL_MAX_CONSECUTIVE_ERRORS);

    // A 4xx is an answer, not a dropped request: no second try.
    apiFetchMock.mockReset();
    apiFetchMock.mockRejectedValue(new ApiError("Not found", 404));
    fireEvent.click(screen.getByRole("button", { name: /Réessayer/ }));
    await advance(0);
    await advance(3 * POLL_INTERVAL_MS);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("L'histoire de ce module n'est pas encore disponible."),
    ).toBeInTheDocument();
  });

  it("treats a failed task as a failure the learner can retry", async () => {
    installFakeTimers();
    loadMock
      .mockResolvedValueOnce({ status: "generating", task_id: "task-1" })
      .mockResolvedValueOnce(moduleStory());
    apiFetchMock.mockResolvedValueOnce({ status: "failed", error: "chapter_generation_failed" });
    renderPanel();

    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "L'histoire n'a pas pu être préparée. Réessaie : les chapitres déjà écrits sont conservés.",
    );
    fireEvent.click(screen.getByRole("button", { name: /Réessayer/ }));
    await advance(0);
    expect(loadMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText(CH1_LINE)).toBeInTheDocument();
  });

  it("treats a failed task marked story_unavailable as unavailable", async () => {
    installFakeTimers();
    loadMock.mockResolvedValueOnce({ status: "generating", task_id: "task-1" });
    apiFetchMock.mockResolvedValueOnce({ status: "failed", error: "story_unavailable" });
    renderPanel();

    await advance(0);
    await advance(POLL_INTERVAL_MS);
    expect(
      screen.getByText("L'histoire de ce module n'est pas encore disponible."),
    ).toBeInTheDocument();
  });
});

describe("ModuleStory — refusals and errors", () => {
  it("shows the subscription screen on 403 subscription_required", async () => {
    loadMock.mockRejectedValue(
      new ApiError("Subscription required", 403, "subscription_required", {
        code: "subscription_required",
        message: "Subscription required",
      }),
    );
    renderPanel();

    expect(await screen.findByText("Abonnement requis")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "S'abonner" })).toHaveAttribute("href", "/subscribe");
    expect(screen.getByRole("link", { name: "Retour au module" })).toHaveAttribute(
      "href",
      `/modules/${MODULE_ID}`,
    );
  });

  it("honours the feature switch: 404 story_mode_disabled", async () => {
    loadMock.mockRejectedValue(
      new ApiError("Story mode is disabled", 404, undefined, { error: "story_mode_disabled" }),
    );
    renderPanel();
    expect(
      await screen.findByText("Le mode histoire n'est pas encore activé sur cette plateforme."),
    ).toBeInTheDocument();
  });

  it.each([
    [409, "story_unavailable"],
    [404, "no_story_content"],
    [404, "module_not_found"],
  ])("says the story is unavailable on %i %s", async (status, code) => {
    loadMock.mockRejectedValue(new ApiError(code, status, undefined, { error: code }));
    renderPanel();
    expect(
      await screen.findByText("L'histoire de ce module n'est pas encore disponible."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Les leçons, quiz et études de cas du module restent disponibles."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Réessayer/ })).not.toBeInTheDocument();
  });

  it("says when the story was not downloaded for offline use", async () => {
    loadMock.mockRejectedValue(
      new OfflineContentNotAvailable(`__module_${MODULE_ID}__`, "story"),
    );
    renderPanel();
    expect(await screen.findByText(/n'a pas été téléchargée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Réessayer/ })).toBeInTheDocument();
  });

  it("offers a retry after an unexpected error", async () => {
    loadMock.mockRejectedValueOnce(new ApiError("boom", 500)).mockResolvedValueOnce(moduleStory());
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: /Réessayer/ }));
    expect(await screen.findByText(CH1_LINE)).toBeInTheDocument();
    expect(loadMock).toHaveBeenCalledTimes(2);
  });
});

describe("ModuleStory — reading", () => {
  it("puts the learner's first name in, on a copy of the cached story", async () => {
    const story = moduleStory();
    const snapshot = JSON.stringify(story);
    loadMock.mockResolvedValue(story);
    renderPanel();

    expect(await screen.findByText(CH1_LINE)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Aminata et l'hygiène" })).toBeInTheDocument();
    expect(screen.getByText("Histoire du module · Module 1")).toBeInTheDocument();
    expect(screen.queryByText(/\{child\}/)).not.toBeInTheDocument();
    expect(JSON.stringify(story)).toBe(snapshot);
  });

  it("holds one chapter at a time", async () => {
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();

    expect(await screen.findByText(CH1_LINE)).toBeInTheDocument();
    expect(screen.getByText("Chapitre 1 sur 4")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Des mains propres" })).toBeInTheDocument();
    expect(screen.queryByText(CH2_LINE)).not.toBeInTheDocument();
    expect(screen.queryByText("Aminata, le quiz t'attend.")).not.toBeInTheDocument();
  });

  it("lists every chapter in the index, with later ones not yet open", async () => {
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();
    await screen.findByText(CH1_LINE);

    const index = screen.getByRole("navigation", { name: "Chapitres" });
    const rows = within(index).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    const current = within(index).getByRole("button", { name: /Des mains propres/ });
    expect(current).toHaveAttribute("aria-current", "step");
    expect(within(rows[2]).getByText("Quiz 1.3")).toBeInTheDocument();
    expect(within(rows[3]).getByText("Étude de cas 1.4")).toBeInTheDocument();
    // Later chapters are listed but cannot be jumped to.
    expect(within(rows[1]).queryByRole("button")).not.toBeInTheDocument();
  });

  it("resumes at the first chapter not finished in this browser", async () => {
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER_ID),
      JSON.stringify({ v: 1, completedUnits: ["unit-1.1"], points: { "unit-1.1": 2 } }),
    );
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();

    expect(await screen.findByText(CH2_LINE)).toBeInTheDocument();
    expect(screen.getByText("Chapitre 2 sur 4")).toBeInTheDocument();
    expect(screen.queryByText(CH1_LINE)).not.toBeInTheDocument();
    // The finished chapter is a summary row with its score, and can be replayed.
    const index = screen.getByRole("navigation", { name: "Chapitres" });
    expect(within(index).getByText("2/2")).toBeInTheDocument();
    expect(within(index).getByRole("button", { name: /Des mains propres/ })).toBeInTheDocument();
  });

  it("never counts a saved score above what its chapter is worth now", async () => {
    // 6 points were earned on lesson 1.1 when its chapter was worth 6; this
    // revision's chapter is worth 4. Lesson 1.2's chapter is worth nothing.
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER_ID),
      JSON.stringify({
        v: 1,
        completedUnits: ["unit-1.1", "unit-1.2"],
        points: { "unit-1.1": 6, "unit-1.2": 3 },
      }),
    );
    const story = moduleStory();
    story.module_story!.revision = "fedcba9876543210";
    story.chapters[0].covers!.max_points = 4;
    loadMock.mockResolvedValue(story);
    renderPanel();

    expect(await screen.findByText("Aminata, le quiz t'attend.")).toBeInTheDocument();
    const index = screen.getByRole("navigation", { name: "Chapitres" });
    expect(within(index).getByText("4/4")).toBeInTheDocument();
    expect(within(index).queryByText("6/4")).not.toBeInTheDocument();
    expect(screen.getByText("4 sur 4 points")).toBeInTheDocument();
  });

  it("still plays when the saved progress is corrupt", async () => {
    window.localStorage.setItem(storyProgressKey(STORY_ID, USER_ID), "{oops");
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();
    expect(await screen.findByText(CH1_LINE)).toBeInTheDocument();
  });

  it("still plays when storage throws, and keeps going in memory", async () => {
    const user = userEvent.setup();
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();
    await screen.findByText(CH1_LINE);

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    await user.click(screen.getByRole("button", { name: "Chapitre suivant" }));
    expect(screen.getByText(CH2_LINE)).toBeInTheDocument();
  });
});

describe("ModuleStory — completion", () => {
  it("completes a lesson once per chapter, never a quiz or a case, then sums up", async () => {
    const user = userEvent.setup();
    // Lesson 1.2 and case 1.4 are already done on the server.
    detailMock.mockResolvedValue(moduleDetail(["1.2", "1.4"]));
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();
    await screen.findByText(CH1_LINE);
    await waitFor(() => expect(detailMock).toHaveBeenCalledWith(MODULE_ID));

    // Chapter 1, lesson 1.1: answer the question right first time.
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(completeMock).toHaveBeenCalledTimes(1);
    expect(completeMock).toHaveBeenCalledWith(MODULE_ID, "1.1", { online: true });
    const status = await screen.findByText("Chapitre terminé !");
    expect(status.closest("[role=status]")).toHaveTextContent("2 sur 2 points");
    expect(await screen.findByText("La leçon 1.1 est marquée comme terminée.")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(storyProgressKey(STORY_ID, USER_ID))!)).toEqual({
      v: 1,
      completedUnits: ["unit-1.1"],
      points: { "unit-1.1": 2 },
    });

    // Chapter 2, lesson 1.2: already completed on the server, so not posted.
    await user.click(screen.getByRole("button", { name: "Chapitre suivant" }));
    expect(screen.getByText("Chapitre 2 sur 4")).toBeInTheDocument();
    // Focus moves to the start of the new chapter.
    await waitFor(() => expect(screen.getByText("Chapitre 2 sur 4")).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByText("Chapitre terminé !")).toBeInTheDocument();

    // Chapter 3, the quiz checkpoint: sends to the quiz, completes nothing.
    await user.click(screen.getByRole("button", { name: "Chapitre suivant" }));
    expect(screen.getByText("Aminata, le quiz t'attend.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Aller au quiz 1.3" })).toHaveAttribute(
      "href",
      `/modules/${MODULE_ID}/units/1.3`,
    );

    // Chapter 4, the case checkpoint: same.
    await user.click(screen.getByRole("button", { name: "Chapitre suivant" }));
    expect(screen.getByText("Aminata, un cas t'attend.")).toBeInTheDocument();
    expect(completeMock).toHaveBeenCalledTimes(1);

    // The summary: only the quiz is still to do.
    await user.click(screen.getByRole("button", { name: "Voir le bilan" }));
    expect(screen.getByText("Histoire terminée !")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Encore à faire" })).toBeInTheDocument();
    const todo = screen.getByRole("link", { name: /Aller au quiz 1.3/ });
    expect(todo).toHaveAttribute("href", `/modules/${MODULE_ID}/units/1.3`);
    expect(screen.queryByRole("link", { name: /Aller à l'étude de cas 1.4/ })).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(storyProgressKey(STORY_ID, USER_ID))!).completedUnits).toEqual([
      "unit-1.1",
      "unit-1.2",
      "unit-1.3",
      "unit-1.4",
    ]);

    // Replaying the first lesson does not post it again.
    const index = screen.getByRole("navigation", { name: "Chapitres" });
    await user.click(within(index).getByRole("button", { name: /Des mains propres/ }));
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(completeMock).toHaveBeenCalledTimes(1);
  });

  it("posts a chapter at most once, even when the server refused it", async () => {
    const user = userEvent.setup();
    vi.spyOn(console, "error").mockImplementation(() => {});
    completeMock.mockRejectedValue(new ApiError("Quiz required", 403, "quiz_required"));
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();
    await screen.findByText(CH1_LINE);

    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    await waitFor(() => expect(completeMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/est marquée comme terminée/)).not.toBeInTheDocument();

    const index = screen.getByRole("navigation", { name: "Chapitres" });
    await user.click(within(index).getByRole("button", { name: /Des mains propres/ }));
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(completeMock).toHaveBeenCalledTimes(1);
  });

  it("queues the completion when the device is offline", async () => {
    const user = userEvent.setup();
    Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => false });
    try {
      completeMock.mockResolvedValue("queued");
      detailMock.mockRejectedValue(new TypeError("Failed to fetch"));
      loadMock.mockResolvedValue(moduleStory());
      renderPanel();
      await screen.findByText(CH1_LINE);

      await user.click(screen.getByRole("button", { name: "Suite" }));
      await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
      expect(completeMock).toHaveBeenCalledWith(MODULE_ID, "1.1", { online: false });
    } finally {
      Object.defineProperty(window.navigator, "onLine", { configurable: true, get: () => true });
    }
  });

  it("never resumes from another learner's progress on a shared phone", async () => {
    // Learner A finished the whole story on this phone, then logged out.
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, "learner-a"),
      JSON.stringify({
        v: 1,
        completedUnits: ["unit-1.1", "unit-1.2", "unit-1.3", "unit-1.4"],
        points: { "unit-1.1": 2 },
      }),
    );
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();

    // Learner u1 starts at the first chapter, with none of A's points.
    expect(await screen.findByText(CH1_LINE)).toBeInTheDocument();
    expect(screen.getByText("Chapitre 1 sur 4")).toBeInTheDocument();
    expect(screen.getByText("0 sur 2 points")).toBeInTheDocument();
    expect(screen.queryByText("Histoire terminée !")).not.toBeInTheDocument();
    expect(screen.queryByText("Toutes les unités de ce module sont terminées.")).not.toBeInTheDocument();
  });

  it("lists a lesson finished here that the server does not have, never 'all done'", async () => {
    // Every chapter finished in this browser; the server has the quiz and the
    // case, but neither lesson (their completions never reached it).
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER_ID),
      JSON.stringify({
        v: 1,
        completedUnits: ["unit-1.1", "unit-1.2", "unit-1.3", "unit-1.4"],
        points: { "unit-1.1": 2 },
      }),
    );
    detailMock.mockResolvedValue(moduleDetail(["1.3", "1.4"]));
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();

    expect(await screen.findByRole("link", { name: /Aller à la leçon 1.1/ })).toHaveAttribute(
      "href",
      `/modules/${MODULE_ID}/units/1.1`,
    );
    expect(screen.getByRole("link", { name: /Aller à la leçon 1.2/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Aller au quiz 1.3/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Toutes les unités de ce module sont terminées.")).not.toBeInTheDocument();
    // Opening the summary posts nothing: the story did not play those chapters now.
    expect(completeMock).not.toHaveBeenCalled();
  });

  it("does not say all is done when the server cannot be asked (offline)", async () => {
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER_ID),
      JSON.stringify({ v: 1, completedUnits: ["unit-1.1", "unit-1.2"], points: {} }),
    );
    detailMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const story = moduleStory();
    story.chapters = story.chapters.slice(0, 2); // lessons only
    loadMock.mockResolvedValue(story);
    renderPanel();

    expect(await screen.findByText("Histoire terminée !")).toBeInTheDocument();
    await waitFor(() => expect(detailMock).toHaveBeenCalled());
    await act(async () => {});
    expect(screen.queryByText("Toutes les unités de ce module sont terminées.")).not.toBeInTheDocument();
  });

  it("opens on the summary when every chapter is done, and says all is done", async () => {
    window.localStorage.setItem(
      storyProgressKey(STORY_ID, USER_ID),
      JSON.stringify({
        v: 1,
        completedUnits: ["unit-1.1", "unit-1.2", "unit-1.3", "unit-1.4"],
        points: { "unit-1.1": 1 },
      }),
    );
    detailMock.mockResolvedValue(moduleDetail(["1.1", "1.2", "1.3", "1.4"]));
    loadMock.mockResolvedValue(moduleStory());
    renderPanel();

    expect(await screen.findByText("Toutes les unités de ce module sont terminées.")).toBeInTheDocument();
    expect(screen.getByText("Histoire terminée !")).toBeInTheDocument();
    expect(screen.getAllByText("1 sur 2 points").length).toBeGreaterThan(0);
    expect(screen.queryByText(CH1_LINE)).not.toBeInTheDocument();
  });
});
