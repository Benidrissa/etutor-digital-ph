/**
 * Predict, observe, name (#2711): the bet is an ungraded `ask`, the demo that
 * follows shows what happened and puts the bet next to it, and the four demo
 * primitives take their verdict from their data and work with taps and keys.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import enMessages from "@/messages/en.json";
import type { StoryEvent } from "@/lib/story-course/events";
import type { Step, StoryCourse } from "@/lib/story-course/types";

import { ConceptVisual } from "./concept-visual";
import { StimulusThumb } from "./stimulus-thumb";
import { StoryPlayer } from "./story-player";
import { clickInCard } from "./story-test-utils";

vi.setConfig({ testTimeout: 20_000 });

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

const PICTURE = "39fe5905-0000-4000-8000-000000000001";
const label = (en: string, fr: string) => ({ en, fr });

function story(steps: Step[]): StoryCourse {
  return {
    format: "story-course/1",
    id: "module-abc-fr",
    course: "Cours",
    week: 1,
    title: { en: "The tables", fr: "Les tables" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "Awa" },
    objectives: [],
    cast: [
      { id: "hero", name: "Awa", kind: "child", art: "nandi" },
      { id: "friend", name: "Kofi", kind: "child", art: "friend" },
    ],
    chapters: [{ id: "c1", title: label("Tables", "Tables"), scenes: [{ id: "s1", place: "classroom", steps }] }],
    questions: [
      {
        id: "p1",
        type: "choice",
        predict: true,
        points: 0,
        prompt: label("Which table is longer?", "Quelle table est la plus longue ?"),
        answer: "c",
        choices: [
          { id: "a", ...label("The left one", "Celle de gauche") },
          { id: "b", ...label("The right one", "Celle de droite") },
          { id: "c", ...label("Same", "Pareilles") },
        ],
        reveal: { right: label("Well bet!", "Bien parié !"), wrong: label("Surprising!", "Surprenant !") },
        stimulus: { source_image_id: PICTURE, alt: label("Two tables", "Deux tables") },
      },
      {
        id: "q1",
        type: "choice",
        prompt: label("What is it?", "Qu'est-ce que c'est ?"),
        answer: "a",
        choices: [
          { id: "a", ...label("An illusion", "Une illusion") },
          { id: "b", ...label("A fact", "Un fait"), misconception: "m1" },
        ],
        stimulus: { source_image_id: PICTURE, alt: label("Two tables", "Deux tables") },
      },
    ],
    rewards: { unit: label("points", "points"), first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  };
}

const STEPS: Step[] = [
  { type: "narrate", en: "A poster.", fr: "Une affiche." },
  { type: "ask", ref: "p1", predict: true },
  {
    type: "show",
    visual: "compare",
    bet: "p1",
    params: { values: [12, 12], labels: [label("left", "gauche"), label("right", "droite")], equal: true, unit: "cm" },
  },
  { type: "concept", title: label("Illusion", "Illusion"), en: ["Eyes can be fooled."], fr: ["Les yeux se trompent."] },
  { type: "ask", ref: "q1" },
  { type: "narrate", en: "The end.", fr: "Fin." },
];

function renderPlayer(onEvent = vi.fn(), onComplete = vi.fn()) {
  render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <StoryPlayer course={story(STEPS)} variant="embedded" onComplete={onComplete} onEvent={onEvent} />
    </NextIntlClientProvider>,
  );
  return { onEvent, onComplete };
}

describe("StoryPlayer — the bet", () => {
  it("plays predict, observe, name; the bet gives no points and is reported anonymously", async () => {
    const user = userEvent.setup();
    const { onEvent, onComplete } = renderPlayer();
    await user.click(screen.getByRole("button", { name: "Suite" }));

    // The bet: a banner of its own, chips, the stimulus in view, no right or wrong said.
    expect(screen.getByText("Ton pari")).toBeInTheDocument();
    expect(screen.getByAltText("Deux tables")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Fais ton pari pour continuer" })).toBeDisabled();
    await clickInCard(user, "Pareilles");
    expect(screen.queryByText(/Pari gagné|Pas cette fois/)).not.toBeInTheDocument();
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ event: "story_prediction", story: "module-abc-fr", question: "p1", matched: true, lang: "fr" }),
    );
    await user.click(screen.getByRole("button", { name: "Suite" }));

    // Observe: the learner measures, then the bet is put next to the verdict, in a live region.
    await user.click(await screen.findByRole("button", { name: "Mesurer" }));
    expect(screen.getByText(/C'est pareil : 12 cm et 12 cm/)).toBeInTheDocument();
    const live = screen.getAllByRole("status").find((el) => /Ton pari : Pareilles/.test(el.textContent ?? ""));
    expect(live).toBeDefined();
    expect(live).toHaveTextContent("Pari gagné.");
    expect(live).toHaveTextContent("Bien parié !");
    expect(live).toHaveAttribute("aria-live", "polite");
    await user.click(screen.getByRole("button", { name: "Suite" }));

    // Name, then a bank question with the stimulus as a thumbnail.
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByAltText("Deux tables")).toBeInTheDocument();
    await clickInCard(user, "Une illusion");
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({ event: "story_first_try", question: "q1", correct: true, attempts: 1 }),
    );
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(onComplete).toHaveBeenCalledWith({ points: 2, maxPoints: 2 });
    const events = onEvent.mock.calls.map((c) => c[0] as StoryEvent);
    expect(events.at(-1)).toMatchObject({ event: "story_chapter_complete", stars: 3 });
    // No free text in anything that was reported.
    expect(JSON.stringify(events)).not.toMatch(/Awa|Kofi|Pareilles|illusion/i);
  });

  it("reports a bet that did not match, and says so after the demo", async () => {
    const user = userEvent.setup();
    const { onEvent } = renderPlayer();
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await clickInCard(user, "Celle de gauche");
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ event: "story_prediction", matched: false }));
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(await screen.findByRole("button", { name: "Mesurer" }));
    expect(screen.getByText(/Pas cette fois\./)).toBeInTheDocument();
    expect(screen.getByText("Surprenant !")).toBeInTheDocument();
  });

  it("reveals the bet on the first Next of a demo left un-acted, and moves on with the second", async () => {
    const user = userEvent.setup();
    renderPlayer();
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await clickInCard(user, "Celle de gauche");
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await screen.findByRole("button", { name: "Mesurer" });
    expect(screen.queryByText(/Pas cette fois\./)).not.toBeInTheDocument();

    // First Next: no measuring, yet the demo shows its answer and the bet is announced.
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByText(/C'est pareil : 12 cm et 12 cm/)).toBeInTheDocument();
    const live = screen.getAllByRole("status").find((el) => /Ton pari : Celle de gauche/.test(el.textContent ?? ""));
    expect(live).toHaveTextContent("Pas cette fois.");
    expect(live).toHaveTextContent("Surprenant !");
    expect(screen.getByRole("button", { name: "Suite" })).toBeEnabled();
    expect(screen.queryByText("Les yeux se trompent.")).not.toBeInTheDocument();

    // Second Next: on to the card.
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByText("Les yeux se trompent.")).toBeInTheDocument();
  });

  it("reports nothing for a chapter opened again to look back at it", async () => {
    const onEvent = vi.fn();
    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <StoryPlayer
          course={story(STEPS)}
          variant="embedded"
          review={{ records: [], points: 0 }}
          onEvent={onEvent}
        />
      </NextIntlClientProvider>,
    );
    expect(onEvent).not.toHaveBeenCalled();
  });
});

describe("the demo primitives", () => {
  function demo(visual: string, params: Record<string, unknown>, onDone = vi.fn()) {
    render(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ConceptVisual visual={visual} params={params} language="en" onDone={onDone} />
      </NextIntlClientProvider>,
    );
    return onDone;
  }

  it("compare: Measure reads the verdict from the numbers", async () => {
    const user = userEvent.setup();
    const onDone = demo("compare", { values: [3, 9], labels: [label("left", "g"), label("right", "d")] });
    await user.click(await screen.findByRole("button", { name: "Measure" }));
    expect(screen.getByText("right is bigger: 3 and 9.")).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith({ correct: true });
  });

  it("annotate: parts are 44px buttons that work with the keyboard; the right one is in the data", async () => {
    const user = userEvent.setup();
    const onDone = demo("annotate", {
      regions: "halves",
      labels: [label("the top", "le haut"), label("the bottom", "le bas")],
      expected: 2,
      source_image_id: PICTURE,
      alt: label("A figure", "Une figure"),
    });
    const part = await screen.findByRole("button", { name: "Part 1: the top" });
    expect(screen.getByAltText("A figure")).toBeInTheDocument();
    expect(part.className).toMatch(/min-h-11/);
    part.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByText("Not quite. Look at: the bottom.")).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith({ correct: false });
  });

  it("sort: each item has one button per box (no dragging), Check compares with the data", async () => {
    const user = userEvent.setup();
    const onDone = demo("sort", {
      bins: [label("measured", "mesuré"), label("guessed", "deviné")],
      items: [
        { label: label("ruler", "règle"), bin: 1 },
        { label: label("eye", "oeil"), bin: 2 },
      ],
    });
    await screen.findByText("Put each thing in its box, then check.");
    expect(screen.getByRole("button", { name: "Check" })).toBeDisabled();
    const groups = screen.getAllByRole("group");
    await user.click(groups[0].querySelectorAll("button")[0]);
    await user.click(groups[1].querySelectorAll("button")[0]); // wrong: the eye is "guessed"
    await user.click(screen.getByRole("button", { name: "Check" }));
    expect(screen.getByText("1 of 2 in the right box.")).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith({ correct: false });
  });

  it("timeline: tap the events in order; the order is the data's", async () => {
    const user = userEvent.setup();
    const onDone = demo("timeline", {
      events: [
        { label: label("first", "premier"), at: 1 },
        { label: label("second", "deuxième"), at: 2 },
      ],
    });
    await user.click(await screen.findByRole("button", { name: /first/ }));
    await user.click(screen.getByRole("button", { name: /second/ }));
    expect(screen.getByText("That is the right order.")).toBeInTheDocument();
    expect(onDone).toHaveBeenCalledWith({ correct: true });
  });
});

describe("the stimulus thumbnail", () => {
  it("takes its alternative text from the figure, in the learner's language", () => {
    render(<StimulusThumb stimulus={{ source_image_id: PICTURE, alt: label("Two tables", "Deux tables") }} lang="fr" />);
    const img = screen.getByAltText("Deux tables");
    expect(img.getAttribute("src")).toContain(`/api/v1/source-images/${PICTURE}/data?lang=fr`);
  });

  it("shows nothing for no picture, and nothing when the picture fails", async () => {
    const { container, rerender } = render(<StimulusThumb stimulus={undefined} lang="fr" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<StimulusThumb stimulus={{ generated_image_id: PICTURE }} lang="en" />);
    const img = container.querySelector("img") as HTMLImageElement;
    img.dispatchEvent(new Event("error"));
    await waitFor(() => expect(container.querySelector("img")).toBeNull());
  });
});

describe("cards with a picture, tasks with a stimulus", () => {
  it("shows the beat's figure beside a card's words, with the figure's own alt text", async () => {
    const user = userEvent.setup();
    const course = story([
      { type: "narrate", en: "A poster.", fr: "Une affiche." },
      {
        type: "concept",
        title: label("Illusion", "Illusion"),
        en: ["Eyes can be fooled."],
        fr: ["Les yeux se trompent."],
        media: { visual: "image", params: { source_image_id: PICTURE, alt: label("Two tables", "Deux tables") } },
      },
      { type: "narrate", en: "The end.", fr: "Fin." },
    ]);
    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <StoryPlayer course={course} variant="embedded" />
      </NextIntlClientProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(document.querySelector("[data-card-media]")).not.toBeNull();
    expect(screen.getByText("Les yeux se trompent.")).toBeInTheDocument();
    expect(screen.getByAltText("Deux tables")).toBeInTheDocument();
  });

  it("shows the stimulus of a paper task as a thumbnail", async () => {
    const { PaperExercise } = await import("./stage/paper-exercise");
    render(
      <NextIntlClientProvider locale="fr" messages={frMessages}>
        <PaperExercise
          exercise={{
            id: "E1",
            part: "A",
            prompt: label("Draw both tables.", "Dessine les deux tables."),
            stimulus: { source_image_id: PICTURE, alt: label("Two tables", "Deux tables") },
          }}
          label="E1"
          target="fr"
          home="en"
          bilingual={false}
          settled={false}
          onMarked={() => {}}
        />
      </NextIntlClientProvider>,
    );
    expect(screen.getByAltText("Deux tables")).toBeInTheDocument();
  });
});
