/**
 * Tests for the lesson's Story tab panel and its place in the media tabs.
 *
 * What matters to a learner on 2G: nothing is downloaded until the Story tab
 * is opened, a story that is still being written is polled until it is ready,
 * a lesson with no valid story says so plainly, and finishing the story
 * completes the lesson exactly once.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch } from "@/lib/api";
import { loadStory, OfflineContentNotAvailable } from "@/lib/offline/content-loader";
import type { StoryCourse } from "@/lib/story-course/types";
import frMessages from "@/messages/fr.json";

import { LessonMediaTabs } from "./lesson-media-tabs";
import { LessonStory } from "./lesson-story";

vi.mock("@/lib/offline/content-loader", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/offline/content-loader")>();
  return { ...actual, loadStory: vi.fn() };
});

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, apiFetch: vi.fn() };
});

// The other panes poll their own endpoints; they are not under test here.
vi.mock("@/components/learning/lesson-audio", () => ({ LessonAudio: () => null }));
vi.mock("@/components/learning/lesson-video", () => ({ LessonVideo: () => null }));

const loadStoryMock = vi.mocked(loadStory);
const apiFetchMock = vi.mocked(apiFetch);

/** A cached lesson story: name-free, the learner written as {child}. */
function lessonStory(): StoryCourse {
  return {
    format: "story-course/1",
    id: "lesson-0123456789abcdef-fr",
    course: "Santé publique",
    week: 1,
    title: { en: "{child} and clean hands", fr: "{child} et les mains propres" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "{child}" },
    objectives: [{ id: "o1", en: "Know when to wash hands", fr: "Savoir quand se laver les mains" }],
    cast: [
      { id: "learner", name: "{child}", kind: "adult", art: "nandi" },
      { id: "margo", name: "Margo", kind: "ai_tutor", art: "margo" },
    ],
    chapters: [
      {
        id: "c1",
        title: { en: "At the clinic", fr: "Au centre de santé" },
        scenes: [
          {
            id: "s1",
            place: "classroom",
            steps: [
              {
                type: "narrate",
                en: "{child} walks into the health centre.",
                fr: "{child} entre dans le centre de santé.",
              },
              { type: "ask", ref: "q1" },
              { type: "narrate", en: "Well done, {child}.", fr: "Bravo, {child}." },
            ],
          },
        ],
      },
    ],
    questions: [
      {
        id: "q1",
        type: "choice",
        objective: "o1",
        prompt: { en: "When do you wash your hands?", fr: "Quand se lave-t-on les mains ?" },
        answer: "a",
        choices: [
          { id: "a", en: "Before touching a patient", fr: "Avant de toucher un patient" },
          {
            id: "b",
            en: "Only when they look dirty",
            fr: "Seulement si elles semblent sales",
            misconception: "m_visible_dirt",
          },
        ],
      },
    ],
    rewards: { unit: { en: "points", fr: "points" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  };
}

const fromApi = <T,>(data: T) => ({ data, source: "api" as const });

function renderPanel(props: Partial<React.ComponentProps<typeof LessonStory>> = {}) {
  const onComplete = props.onComplete ?? vi.fn();
  const onActivelyGeneratingChange = props.onActivelyGeneratingChange ?? vi.fn();
  const element = (active: boolean) => (
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <LessonStory
        moduleId="mod-1"
        unitId="1.2"
        language="fr"
        active={active}
        onComplete={onComplete}
        onActivelyGeneratingChange={onActivelyGeneratingChange}
      />
    </NextIntlClientProvider>
  );
  const view = render(element(props.active ?? true));
  return {
    ...view,
    onComplete,
    onActivelyGeneratingChange,
    setActive: (active: boolean) => view.rerender(element(active)),
  };
}

beforeEach(() => {
  loadStoryMock.mockReset();
  apiFetchMock.mockReset();
  window.localStorage.setItem(
    "user",
    JSON.stringify({
      id: "u1",
      email: null,
      name: "Aminata Diallo",
      preferred_language: "fr",
      current_level: 1,
    }),
  );
});

afterEach(() => {
  vi.useRealTimers();
  window.localStorage.clear();
});

describe("LessonStory", () => {
  it("does not fetch while its tab is inactive, then fetches once it opens", async () => {
    loadStoryMock.mockResolvedValue(fromApi(lessonStory()));
    const { setActive, container } = renderPanel({ active: false });

    await act(async () => {});
    expect(loadStoryMock).not.toHaveBeenCalled();
    expect(container).toBeEmptyDOMElement();

    setActive(true);
    await waitFor(() => expect(loadStoryMock).toHaveBeenCalledTimes(1));
    expect(loadStoryMock).toHaveBeenCalledWith("mod-1", "1.2", "fr");
    await screen.findByText("Aminata entre dans le centre de santé.");

    // Leaving and coming back keeps the story; nothing is downloaded again.
    setActive(false);
    setActive(true);
    await act(async () => {});
    expect(loadStoryMock).toHaveBeenCalledTimes(1);
  });

  it("renders the player with the learner's first name on a 200", async () => {
    const story = lessonStory();
    const snapshot = JSON.stringify(story);
    loadStoryMock.mockResolvedValue(fromApi(story));
    renderPanel();

    expect(await screen.findByText("Aminata entre dans le centre de santé.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Aminata et les mains propres" })).toBeInTheDocument();
    expect(screen.queryByText(/\{child\}/)).not.toBeInTheDocument();
    // The cached document itself stays name-free.
    expect(JSON.stringify(story)).toBe(snapshot);
  });

  it("polls the content status on a 202, then renders the story", async () => {
    vi.useFakeTimers();
    loadStoryMock
      .mockResolvedValueOnce(fromApi({ status: "generating", task_id: "task-9" }))
      .mockResolvedValueOnce(fromApi(lessonStory()));
    apiFetchMock
      .mockResolvedValueOnce({ status: "pending" })
      .mockResolvedValueOnce({ status: "complete", content_id: "s-1" });
    const { onActivelyGeneratingChange } = renderPanel();

    await act(async () => {});
    expect(screen.getByText("Écriture de l'histoire de cette leçon…")).toBeInTheDocument();
    expect(onActivelyGeneratingChange).toHaveBeenLastCalledWith(true);
    expect(apiFetchMock).not.toHaveBeenCalled();

    // First poll: still running.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(apiFetchMock).toHaveBeenLastCalledWith("/api/v1/content/status/task-9");
    expect(screen.getByText("Écriture de l'histoire de cette leçon…")).toBeInTheDocument();

    // Second poll: done — the story is re-read through the offline loader.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
    expect(loadStoryMock).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Aminata entre dans le centre de santé.")).toBeInTheDocument();
    expect(onActivelyGeneratingChange).toHaveBeenLastCalledWith(false);
  });

  it("shows a friendly message on 409 story_unavailable", async () => {
    loadStoryMock.mockRejectedValue(
      new ApiError("No valid story", 409, undefined, {
        error: "story_unavailable",
        message: "No valid story",
      }),
    );
    renderPanel();

    expect(
      await screen.findByText("L'histoire de cette leçon n'est pas encore disponible."),
    ).toBeInTheDocument();
    expect(screen.getByText("La leçon reste disponible en lecture, en audio et en vidéo.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Réessayer/ })).not.toBeInTheDocument();
  });

  it("treats a failed generation task marked story_unavailable the same way", async () => {
    vi.useFakeTimers();
    loadStoryMock.mockResolvedValueOnce(fromApi({ status: "generating", task_id: "task-1" }));
    apiFetchMock.mockResolvedValueOnce({ status: "failed", error: "story_unavailable" });
    renderPanel();

    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(screen.getByText("L'histoire de cette leçon n'est pas encore disponible.")).toBeInTheDocument();
  });

  it("offers a retry after an unexpected error", async () => {
    loadStoryMock
      .mockRejectedValueOnce(new ApiError("boom", 500))
      .mockResolvedValueOnce(fromApi(lessonStory()));
    renderPanel();

    const retry = await screen.findByRole("button", { name: /Réessayer/ });
    expect(screen.getByRole("alert")).toHaveTextContent("L'histoire n'a pas pu être préparée.");
    fireEvent.click(retry);

    expect(await screen.findByText("Aminata entre dans le centre de santé.")).toBeInTheDocument();
    expect(loadStoryMock).toHaveBeenCalledTimes(2);
  });

  it("says when the story was not downloaded for offline use", async () => {
    loadStoryMock.mockRejectedValue(new OfflineContentNotAvailable("1.2", "story"));
    renderPanel();
    expect(await screen.findByText(/n'a pas été téléchargée/)).toBeInTheDocument();
  });

  it("honours the backend's feature switch: 404 story_mode_disabled (X2)", async () => {
    loadStoryMock.mockRejectedValue(
      new ApiError("Story mode is disabled", 404, undefined, { error: "story_mode_disabled" }),
    );
    renderPanel();
    expect(
      await screen.findByText("Le mode histoire n'est pas encore activé sur cette plateforme."),
    ).toBeInTheDocument();
    expect(screen.queryByText("L'histoire de cette leçon n'est pas encore disponible.")).not.toBeInTheDocument();
  });

  it("maps by detail.error whatever the status", async () => {
    loadStoryMock.mockRejectedValue(
      new ApiError("disabled", 403, undefined, { error: "story_mode_disabled" }),
    );
    renderPanel();
    expect(
      await screen.findByText("Le mode histoire n'est pas encore activé sur cette plateforme."),
    ).toBeInTheDocument();
  });

  it("says a quiz or case-study unit has no story (404 not_a_lesson, X3)", async () => {
    loadStoryMock.mockRejectedValue(
      new ApiError("Not a lesson", 404, undefined, { error: "not_a_lesson" }),
    );
    renderPanel();
    expect(
      await screen.findByText("L'histoire de cette leçon n'est pas encore disponible."),
    ).toBeInTheDocument();
  });

  it("does not call a paywall 403 'switched off'", async () => {
    loadStoryMock.mockRejectedValue(
      new ApiError("Subscription required", 403, "subscription_required", {
        code: "subscription_required",
      }),
    );
    renderPanel();
    expect(
      await screen.findByText("L'histoire de cette leçon n'est pas encore disponible."),
    ).toBeInTheDocument();
  });

  it("completes the lesson once when the learner reaches the end", async () => {
    const user = userEvent.setup();
    loadStoryMock.mockResolvedValue(fromApi(lessonStory()));
    const { onComplete } = renderPanel();

    await user.click(await screen.findByRole("button", { name: "Continuer" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(onComplete).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    expect(screen.getByText("Bravo, Aminata.")).toBeInTheDocument();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });
});

describe("LessonMediaTabs — Story tab", () => {
  function renderTabs(onStoryComplete = vi.fn()) {
    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <LessonMediaTabs
          lessonId="lesson-1"
          moduleId="mod-1"
          unitId="1.2"
          language="fr"
          readPane={<p>Corps de la leçon</p>}
          onStoryComplete={onStoryComplete}
        />
      </NextIntlClientProvider>,
    );
    return onStoryComplete;
  }

  it("downloads nothing until the Story tab is opened", async () => {
    loadStoryMock.mockResolvedValue(fromApi(lessonStory()));
    renderTabs();

    expect(screen.getByRole("tab", { name: /Histoire/ })).toBeInTheDocument();
    await act(async () => {});
    expect(loadStoryMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("tab", { name: /Histoire/ }));
    await waitFor(() => expect(loadStoryMock).toHaveBeenCalledWith("mod-1", "1.2", "fr"));
    expect(await screen.findByText("Aminata entre dans le centre de santé.")).toBeInTheDocument();
  });

  it("passes the story's completion up to the lesson", async () => {
    const user = userEvent.setup();
    loadStoryMock.mockResolvedValue(fromApi(lessonStory()));
    const onStoryComplete = renderTabs();

    await user.click(screen.getByRole("tab", { name: /Histoire/ }));
    await user.click(await screen.findByRole("button", { name: "Continuer" }));
    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    expect(onStoryComplete).toHaveBeenCalledTimes(1);
  });
});
