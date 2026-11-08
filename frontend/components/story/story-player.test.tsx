/**
 * Component tests for the story player: language keying (contract C1),
 * completion (contract C7), the bilingual default inside a lesson, and a full
 * score reachable through questions, a game and self-marked paper exercises
 * (contract X6).
 *
 * C1 is the bug these guard: the player used to print `step.en` first no
 * matter what, so a French learner read every line of a French-target story in
 * English with the French in small italics underneath.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { Step, StoryCourse } from "@/lib/story-course/types";

import { EMBEDDED_BILINGUAL_KEY, StoryPlayer } from "./story-player";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

/** A lesson story generated for a French learner: target fr, home en. */
function frenchStory(extraSteps: Step[] = []): StoryCourse {
  return {
    format: "story-course/1",
    id: "lesson-0123456789abcdef-fr",
    course: "Santé publique",
    week: 1,
    title: { en: "Clean hands save lives", fr: "Des mains propres sauvent des vies" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "Awa" },
    objectives: [{ id: "o1", en: "Know when to wash hands", fr: "Savoir quand se laver les mains" }],
    cast: [
      { id: "learner", name: "Awa", kind: "adult", art: "nandi" },
      { id: "mentor", name: "Dr Kaboré", kind: "adult", art: "mr_kabore" },
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
                en: "Awa walks into the health centre.",
                fr: "Awa entre dans le centre de santé.",
              },
              { type: "say", who: "mentor", mood: "talk", en: "Hello Awa!", fr: "Bonjour Awa !" },
              {
                type: "concept",
                title: { en: "The five moments", fr: "Les cinq moments" },
                en: ["Wash before touching a patient."],
                fr: ["Se laver les mains avant de toucher un patient."],
              },
              { type: "ask", ref: "q1" },
              ...extraSteps,
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
        explanation: { en: "Germs are invisible.", fr: "Les germes sont invisibles." },
      },
    ],
    rewards: { unit: { en: "points", fr: "points" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  };
}

function renderPlayer(
  course: StoryCourse,
  onComplete = vi.fn(),
  { locale = "fr" as "fr" | "en", variant = "embedded" as "embedded" | "page" } = {},
) {
  const messages = locale === "fr" ? frMessages : enMessages;
  const view = render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <StoryPlayer course={course} variant={variant} onComplete={onComplete} />
    </NextIntlClientProvider>,
  );
  return { ...view, onComplete, messages, locale };
}

/** True when `a` comes before `b` in document order. */
function precedes(a: Element, b: Element): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("StoryPlayer — language keying (C1)", () => {
  it("shows a French-target story in French first, English beneath", async () => {
    const user = userEvent.setup();
    // The standalone week opens bilingual (the embedded lesson one does not).
    renderPlayer(frenchStory(), vi.fn(), { variant: "page" });

    expect(screen.getByRole("heading", { name: "Des mains propres sauvent des vies" })).toBeInTheDocument();

    const frNarrate = screen.getByText("Awa entre dans le centre de santé.");
    const enNarrate = screen.getByText("Awa walks into the health centre.");
    expect(precedes(frNarrate, enNarrate)).toBe(true);
    expect(frNarrate).toHaveAttribute("lang", "fr");
    expect(enNarrate).toHaveAttribute("lang", "en");

    await user.click(screen.getByRole("button", { name: "Continuer" }));
    const frSay = screen.getByText("Bonjour Awa !");
    const enSay = screen.getByText("Hello Awa!");
    expect(precedes(frSay, enSay)).toBe(true);

    await user.click(screen.getByRole("button", { name: "Continuer" }));
    const frRow = screen.getByText("Se laver les mains avant de toucher un patient.");
    const enRow = screen.getByText("Wash before touching a patient.");
    expect(precedes(frRow, enRow)).toBe(true);
  });

  it("shows only the target language once bilingual mode is off", async () => {
    const user = userEvent.setup();
    renderPlayer(frenchStory(), vi.fn(), { variant: "page" });

    await user.click(screen.getByRole("button", { name: /Afficher les deux langues/ }));

    expect(screen.getByText("Awa entre dans le centre de santé.")).toBeInTheDocument();
    expect(screen.queryByText("Awa walks into the health centre.")).not.toBeInTheDocument();
  });

  it("keeps an English-target week reading English first", () => {
    const story = frenchStory();
    story.languages = { target: "en", home: "fr" };
    renderPlayer(story, vi.fn(), { locale: "en", variant: "page" });

    const enNarrate = screen.getByText("Awa walks into the health centre.");
    const frNarrate = screen.getByText("Awa entre dans le centre de santé.");
    expect(precedes(enNarrate, frNarrate)).toBe(true);
  });

  it("labels choices in the target language", async () => {
    const user = userEvent.setup();
    renderPlayer(frenchStory());
    for (let i = 0; i < 3; i += 1) {
      await user.click(screen.getByRole("button", { name: "Continuer" }));
    }
    expect(screen.getByRole("button", { name: "Avant de toucher un patient" })).toBeInTheDocument();
  });
});

describe("StoryPlayer — completion (C7)", () => {
  it("fires onComplete exactly once, at the end", async () => {
    const user = userEvent.setup();
    const story = frenchStory([{ type: "narrate", en: "The end.", fr: "Fin." }]);
    const { onComplete, rerender } = renderPlayer(story);

    for (let i = 0; i < 3; i += 1) {
      await user.click(screen.getByRole("button", { name: "Continuer" }));
    }
    expect(onComplete).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(onComplete).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith({ points: 2, maxPoints: 2 });
    expect(screen.getByText("Histoire terminée !")).toBeInTheDocument();
    expect(screen.getByText("2 sur 2 points")).toBeInTheDocument();

    // A parent re-rendering with a fresh callback must not complete twice.
    const second = vi.fn();
    rerender(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <StoryPlayer course={story} variant="embedded" onComplete={second} />
      </NextIntlClientProvider>,
    );
    expect(second).not.toHaveBeenCalled();
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("waits for a question on the last step to be answered", async () => {
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(frenchStory());

    for (let i = 0; i < 3; i += 1) {
      await user.click(screen.getByRole("button", { name: "Continuer" }));
    }
    // The last step is the question: on screen, but not answered yet.
    expect(screen.getByRole("button", { name: "Réponds pour continuer" })).toBeDisabled();
    expect(onComplete).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("keeps the Continue control in the page flow when embedded", () => {
    const { container } = renderPlayer(frenchStory());
    expect(container.querySelector(".fixed")).toBeNull();
  });

  it("keeps the fixed Continue bar on the standalone page", () => {
    const { container } = renderPlayer(frenchStory(), vi.fn(), { variant: "page" });
    expect(container.querySelector(".fixed")).not.toBeNull();
    expect(screen.getByText(/Semaine 1/)).toBeInTheDocument();
  });
});

describe("StoryPlayer — bilingual default", () => {
  it("starts with the second language off inside a lesson, and remembers the toggle", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPlayer(frenchStory());

    expect(screen.getByText("Awa entre dans le centre de santé.")).toBeInTheDocument();
    expect(screen.queryByText("Awa walks into the health centre.")).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /Afficher les deux langues/ });
    expect(toggle).toHaveAttribute("aria-pressed", "false");

    await user.click(toggle);
    expect(screen.getByText("Awa walks into the health centre.")).toBeInTheDocument();
    expect(window.localStorage.getItem(EMBEDDED_BILINGUAL_KEY)).toBe("on");

    // The next lesson story opens the way she left it.
    unmount();
    renderPlayer(frenchStory());
    expect(screen.getByText("Awa walks into the health centre.")).toBeInTheDocument();
  });

  it("keeps the standalone week bilingual by default, whatever the lesson choice", () => {
    window.localStorage.setItem(EMBEDDED_BILINGUAL_KEY, "off");
    renderPlayer(frenchStory(), vi.fn(), { variant: "page" });
    expect(screen.getByText("Awa walks into the health centre.")).toBeInTheDocument();
  });

  it("falls back to off when storage is unavailable", async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    renderPlayer(frenchStory());
    expect(screen.queryByText("Awa walks into the health centre.")).not.toBeInTheDocument();

    // The toggle still works for this visit.
    await user.click(screen.getByRole("button", { name: /Afficher les deux langues/ }));
    expect(screen.getByText("Awa walks into the health centre.")).toBeInTheDocument();
  });
});

/**
 * A lesson story with every kind of scored step: a question (2), a catch game
 * with two right items (2) and two paper exercises (3 + 1 marks). The
 * validator's max_points is their sum, 8.
 */
function fullStory(): StoryCourse {
  const story = frenchStory([
    { type: "game", ref: "g1" },
    { type: "photo", ref: "e1" },
    { type: "photo", ref: "e2" },
    { type: "narrate", en: "The end.", fr: "Fin." },
  ]);
  story.minigames = [
    {
      id: "g1",
      engine: "catch",
      title: { en: "Clean hands", fr: "Mains propres" },
      instruction: { en: "Tap every right moment.", fr: "Touche chaque bon moment." },
      points: { per_correct: 1 },
      timer_s: 30,
      rounds: [
        {
          prompt: { en: "When?", fr: "Quand ?" },
          items: [
            { label: { en: "Before a patient", fr: "Avant un patient" }, correct: true },
            { label: { en: "After a patient", fr: "Après un patient" }, correct: true },
            {
              label: { en: "Only if dirty", fr: "Seulement si sales" },
              correct: false,
              trap: "m_visible_dirt",
            },
          ],
        },
      ],
    },
  ];
  story.exercises = [
    {
      id: "e1",
      part: "A",
      marks: 3,
      prompt: { en: "List the five moments.", fr: "Cite les cinq moments." },
      working: { en: ["1. Before a patient"], fr: ["1. Avant un patient"] },
      mark_scheme: [{ code: "B1", en: "Each moment", fr: "Chaque moment" }],
    },
    {
      id: "e2",
      part: "B",
      marks: 1,
      prompt: { en: "How long should you rub?", fr: "Combien de temps frotter ?" },
      working: { en: ["20 seconds"], fr: ["20 secondes"] },
    },
  ];
  story.checks = { max_points: 8 };
  return story;
}

/** Click through to the question and answer it right first time. */
async function answerQuestion(user: ReturnType<typeof userEvent.setup>) {
  for (let i = 0; i < 3; i += 1) {
    await user.click(screen.getByRole("button", { name: "Continuer" }));
  }
  await user.click(screen.getByRole("button", { name: "Avant de toucher un patient" }));
  await user.click(screen.getByRole("button", { name: "Continuer" }));
}

describe("StoryPlayer — paper exercises are self-marked (X6)", () => {
  it("reaches checks.max_points and three stars on a perfect run", async () => {
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(fullStory());

    await answerQuestion(user);

    // The game: catch both right items.
    await user.click(screen.getByRole("button", { name: "Commencer" }));
    await user.click(screen.getByRole("button", { name: "Avant un patient" }));
    await user.click(screen.getByRole("button", { name: "Après un patient" }));
    expect(await screen.findByText("Partie terminée — +2", {}, { timeout: 3000 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    // The first exercise: done on paper, the worked answer opens, she marks it.
    expect(screen.getByRole("button", { name: "Réponds pour continuer" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Fait sur papier" }));
    expect(screen.getByText("1. Avant un patient")).toBeInTheDocument();
    const gotIt = screen.getByRole("button", { name: "J'ai réussi (+3)" });
    // 44px touch target (min-h-11).
    expect(gotIt.className).toMatch(/min-h-11/);
    expect(screen.getByRole("button", { name: "Pas encore" }).className).toMatch(/min-h-11/);
    // Not settled until she marks it.
    expect(screen.getByRole("button", { name: "Réponds pour continuer" })).toBeDisabled();
    await user.click(gotIt);
    expect(screen.getByText("Tu t'es donné 3 sur 3.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /J'ai réussi/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    // The second exercise.
    await user.click(screen.getByRole("button", { name: "Fait sur papier" }));
    await user.click(screen.getByRole("button", { name: "J'ai réussi (+1)" }));
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith({ points: 8, maxPoints: 8 });
    expect(screen.getByText("8 sur 8 points")).toBeInTheDocument();
    expect(screen.getByText("⭐⭐⭐")).toBeInTheDocument();
  });

  it("awards nothing for 'Not yet' and still lets the story go on", async () => {
    const user = userEvent.setup();
    const story = fullStory();
    // Only the exercise: question first, then straight to the paper.
    story.chapters[0].scenes[0].steps = story.chapters[0].scenes[0].steps.filter(
      (step) => step.type !== "game",
    );
    const { onComplete } = renderPlayer(story);

    await answerQuestion(user);
    await user.click(screen.getByRole("button", { name: "Fait sur papier" }));
    await user.click(screen.getByRole("button", { name: "Pas encore" }));
    expect(screen.getByText("Tu t'es donné 0 sur 3.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Continuer" }));
    await user.click(screen.getByRole("button", { name: "Fait sur papier" }));
    await user.click(screen.getByRole("button", { name: "Pas encore" }));
    await user.click(screen.getByRole("button", { name: "Continuer" }));

    expect(onComplete).toHaveBeenCalledWith({ points: 2, maxPoints: 8 });
  });

  it("keeps the worked answer hideable after marking", async () => {
    const user = userEvent.setup();
    const story = fullStory();
    story.chapters[0].scenes[0].steps = story.chapters[0].scenes[0].steps.filter(
      (step) => step.type !== "game",
    );
    renderPlayer(story);

    await answerQuestion(user);
    await user.click(screen.getByRole("button", { name: "Fait sur papier" }));
    await user.click(screen.getByRole("button", { name: /J'ai réussi/ }));
    await user.click(screen.getByRole("button", { name: "Masquer le raisonnement" }));
    expect(screen.queryByText("1. Avant un patient")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Afficher le raisonnement" }));
    expect(screen.getByText("1. Avant un patient")).toBeInTheDocument();
  });
});
