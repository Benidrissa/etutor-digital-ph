/**
 * Component tests for the story player: language keying (contract C1) and
 * completion (contract C7).
 *
 * C1 is the bug these guard: the player used to print `step.en` first no
 * matter what, so a French learner read every line of a French-target story in
 * English with the French in small italics underneath.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { Step, StoryCourse } from "@/lib/story-course/types";

import { StoryPlayer } from "./story-player";

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
    renderPlayer(frenchStory());

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
    renderPlayer(frenchStory());

    await user.click(screen.getByRole("button", { name: /Afficher les deux langues/ }));

    expect(screen.getByText("Awa entre dans le centre de santé.")).toBeInTheDocument();
    expect(screen.queryByText("Awa walks into the health centre.")).not.toBeInTheDocument();
  });

  it("keeps an English-target week reading English first", () => {
    const story = frenchStory();
    story.languages = { target: "en", home: "fr" };
    renderPlayer(story, vi.fn(), { locale: "en" });

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
