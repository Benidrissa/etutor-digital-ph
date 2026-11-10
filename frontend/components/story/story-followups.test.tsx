/**
 * The #2686 post-merge fixes (#2688): Previous can no longer hand out fresh
 * tries, the full-screen figure no longer drives the story behind it, the
 * title card never sits under props, and the props degrade gracefully.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import type { Minigame, Prop, StoryCourse } from "@/lib/story-course/types";

import { LookCloser } from "./stage/look-closer";
import { pictureFor } from "./stage/props";
import { StoryPlayer } from "./story-player";
import { cardReady, clickInCard } from "./story-test-utils";

vi.setConfig({ testTimeout: 20_000 });

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const FIGURE_ID = "3f2c9a1e-0b7d-4c55-9e2a-1d2f3a4b5c6d";

function baseStory(steps: StoryCourse["chapters"][number]["scenes"][number]["steps"]): StoryCourse {
  return {
    format: "story-course/1",
    id: "module-x-fr",
    course: "Biologie",
    week: 1,
    title: { en: "Life", fr: "La vie" },
    languages: { target: "fr", home: "en" },
    learner: { first_name: "Aminata" },
    objectives: [],
    cast: [
      { id: "mentor", name: "M. Kaboré", kind: "adult", art: "mr_kabore" },
      { id: "peer", name: "Awa", kind: "child", art: "friend" },
    ],
    chapters: [
      {
        id: "ch1",
        title: { en: "Signs of life", fr: "Les signes du vivant" },
        scenes: [{ id: "s1", place: "classroom", steps }],
      },
    ],
    questions: [
      {
        id: "q1",
        type: "choice",
        prompt: { en: "Which is alive?", fr: "Lequel est vivant ?" },
        answer: "a",
        choices: [
          { id: "a", en: "The frog", fr: "La grenouille" },
          { id: "b", en: "The stone", fr: "Le caillou" },
          { id: "c", en: "The chair", fr: "La chaise" },
        ],
        hints: [{ en: "Think of what eats.", fr: "Pense à ce qui mange." }],
        explanation: { en: "A frog feeds and grows.", fr: "Une grenouille se nourrit et grandit." },
      },
    ],
    rewards: { unit: { en: "mangoes", fr: "mangues" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  } as StoryCourse;
}

function renderPlayer(course: StoryCourse, props: Partial<React.ComponentProps<typeof StoryPlayer>> = {}) {
  const onComplete = vi.fn();
  const view = render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <StoryPlayer course={course} variant="embedded" onComplete={onComplete} {...props} />
    </NextIntlClientProvider>,
  );
  return { ...view, onComplete };
}

const next = () => screen.getByRole("button", { name: "Suite" });
const previous = () => screen.getByRole("button", { name: "Précédent" });
const stageBox = () => screen.getByTestId("story-stage").firstElementChild as HTMLElement;

describe("Previous never hands out a fresh try (#2688)", () => {
  const steps = [
    { type: "narrate" as const, en: "A mystery awaits.", fr: "Un mystère t'attend." },
    { type: "say" as const, who: "mentor", en: "Look closely.", fr: "Observe bien." },
    { type: "ask" as const, ref: "q1" },
    { type: "say" as const, who: "peer", en: "It moved!", fr: "Elle a bougé !" },
  ];

  it("keeps a wrong first answer and its hint across Previous and Next", async () => {
    // The review's repro: wrong, Previous, Next, wrong, Previous, Next, right
    // used to score a first try (+2). Two wrong answers settle it at 0.
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(baseStory(steps), { chapterId: "ch1", maxPoints: 2 });
    await user.click(next());
    await user.click(next());
    await clickInCard(user, "Le caillou");
    expect(screen.getByText("Pense à ce qui mange.")).toBeInTheDocument();

    await user.click(previous());
    await user.click(next());
    // The same try, the same hint: this is the second try now.
    expect(screen.getByText("Pense à ce qui mange.")).toBeInTheDocument();
    await clickInCard(user, "La chaise");
    expect(screen.getByText("Une grenouille se nourrit et grandit.")).toBeInTheDocument();
    expect(screen.queryByText(/\+2 mangues/)).not.toBeInTheDocument();
    // Settled: the right answer can no longer be tried.
    expect(screen.getByRole("button", { name: /La grenouille/ })).toBeDisabled();

    await user.click(next());
    expect(onComplete).toHaveBeenCalledWith({ points: 0, maxPoints: 2 });
  });

  it("scores a right second try once, even after Previous and Next", async () => {
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(baseStory(steps), { chapterId: "ch1", maxPoints: 2 });
    await user.click(next());
    await user.click(next());
    await clickInCard(user, "Le caillou");
    await user.click(previous());
    await user.click(next());
    await clickInCard(user, "La grenouille");
    expect(screen.getByText("+1 mangues")).toBeInTheDocument();
    await user.click(next());
    expect(onComplete).toHaveBeenCalledWith({ points: 1, maxPoints: 2 });
  });

  it("waits for a running game to end before going back", async () => {
    const user = userEvent.setup();
    const story = baseStory([
      { type: "narrate", en: "Play!", fr: "On joue !" },
      { type: "game", ref: "g1" },
      { type: "say", who: "peer", en: "Done.", fr: "Fini." },
    ]);
    const game: Minigame = {
      id: "g1",
      engine: "catch",
      title: { en: "Signs of life", fr: "Les signes du vivant" },
      instruction: { en: "Tap what is alive.", fr: "Touche ce qui est vivant." },
      points: { per_correct: 1 },
      timer_s: 30,
      rounds: [
        {
          items: [
            { label: { en: "It grows", fr: "Il grandit" }, correct: true },
            { label: { en: "It shines", fr: "Il brille" }, correct: false },
          ],
        },
      ],
    } as Minigame;
    story.minigames = [game];
    story.questions = [];
    renderPlayer(story, { chapterId: "ch1", maxPoints: 1 });
    await user.click(next());
    await cardReady();
    expect(previous()).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Commencer" }));

    // Running: Previous, ← and a swipe all wait.
    expect(previous()).toBeDisabled();
    await user.keyboard("{ArrowLeft}");
    fireEvent.touchStart(stageBox(), { touches: [{ clientX: 40, clientY: 100 }] });
    fireEvent.touchEnd(stageBox(), { changedTouches: [{ clientX: 160, clientY: 105 }] });
    expect(screen.getByText("Manche 1 / 1")).toBeInTheDocument();

    // Over: Previous works again, and the game comes back finished.
    await user.click(screen.getByRole("button", { name: /Il grandit/ }));
    // The round clears 0.6 s after its last right tap: headroom on a busy runner.
    await waitFor(() => expect(previous()).toBeEnabled(), { timeout: 4000 });
    await user.click(previous());
    await user.click(next());
    expect(screen.queryByRole("button", { name: "Commencer" })).not.toBeInTheDocument();
    expect(screen.getByText(/Partie terminée/)).toBeInTheDocument();
  });

  it("keeps the keyboard in the story when Previous reaches the first line", async () => {
    const user = userEvent.setup();
    renderPlayer(baseStory(steps), { chapterId: "ch1", maxPoints: 2 });
    await user.click(next());
    previous().focus();
    await user.keyboard("{Enter}");
    expect(previous()).toBeDisabled();
    await waitFor(() => expect(next()).toHaveFocus());
  });
});

describe("The full-screen figure on a story step (#2688)", () => {
  function figureStory(): StoryCourse {
    return baseStory([
      { type: "narrate", en: "Look.", fr: "Regarde." },
      {
        type: "show",
        visual: "image",
        params: { source_image_id: FIGURE_ID, figure_number: "Figure 2.1", alt: { en: "Hands", fr: "Des mains" } },
      },
      { type: "say", who: "peer", en: "I see!", fr: "Je vois !" },
    ]);
  }

  async function openViewer(user: ReturnType<typeof userEvent.setup>) {
    await user.click(next());
    const thumb = screen.getByRole("button", { name: /plein écran/i });
    await user.click(thumb);
    return { thumb, viewer: screen.getByRole("dialog") };
  }

  it("does not move the story when swiped or tapped", async () => {
    const user = userEvent.setup();
    renderPlayer(figureStory());
    const { viewer } = await openViewer(user);

    fireEvent.touchStart(viewer, { touches: [{ clientX: 40, clientY: 200 }] });
    fireEvent.touchEnd(viewer, { changedTouches: [{ clientX: 200, clientY: 205 }] });
    // Still on the figure, still open: no "back" behind it.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText("Regarde.")).not.toBeInTheDocument();

    // A tap on the backdrop closes the viewer, and only that.
    await user.click(screen.getByRole("dialog"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /plein écran/i })).toBeInTheDocument();
    expect(screen.queryByText("Je vois !")).not.toBeInTheDocument();
  });

  it("keeps the focus inside, closes on Esc, gives the focus back, and leaves the page behind inert", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(figureStory());
    const { thumb } = await openViewer(user);
    const close = screen.getByRole("button", { name: /Fermer/i });
    expect(close).toHaveFocus();
    // The page behind takes no focus, clicks or reading.
    expect(container).toHaveAttribute("inert");
    await user.tab();
    expect(close).toHaveFocus();
    // The story's own keys do nothing behind it.
    await user.keyboard("{ArrowRight}");
    expect(screen.queryByText("Je vois !")).not.toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(container).not.toHaveAttribute("inert");
    await waitFor(() => expect(thumb).toHaveFocus());
  });
});

/** A chapter that opens on a narrator's line about a snail on the ground. */
function propsOpener(extra: Prop[] = [], named: string[] = ["snail"]): StoryCourse {
  const story = baseStory([
    { type: "narrate", en: "A snail crawls past.", fr: "Un escargot passe.", props: named },
    { type: "say", who: "peer", en: "Look!", fr: "Regarde !" },
  ]);
  story.props = [
    { id: "snail", label: { en: "a snail", fr: "un escargot" }, query: "garden snail", kind: "real", emoji: "🐌", at: "ground", size: "s" },
    ...extra,
  ];
  story.chapters[0].scenes[0].props = story.props.map((prop) => prop.id);
  return story;
}

describe("Props and the title card (#2688)", () => {
  it("shows a narrated opener's title during its beat only, never under the props", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(propsOpener());
    // The beat: the title alone, no props yet.
    expect(container.querySelector("[data-title-card]")).not.toBeNull();
    expect(container.querySelector("[data-prop]")).toBeNull();
    await user.click(next());
    // The line and its props: the title is gone.
    expect(container.querySelector("[data-title-card]")).toBeNull();
    expect(container.querySelector('[data-prop="snail"]')).not.toBeNull();
    expect(document.querySelector('[data-step-panel="narrate"]')).toHaveAttribute("data-at", "top");
    // Seen again with Previous: still no title over the props.
    await user.click(next());
    await user.click(previous());
    expect(container.querySelector("[data-title-card]")).toBeNull();
  });

  it("keeps the caption at the bottom when something is in the sky", async () => {
    const user = userEvent.setup();
    const sun: Prop = { id: "sun", label: { en: "the sun", fr: "le soleil" }, query: "sun", kind: "sticker", emoji: "☀️", at: "sky" };
    renderPlayer(propsOpener([sun], ["snail", "sun"]));
    await user.click(next());
    expect(document.querySelector('[data-prop="sun"]')).not.toBeNull();
    expect(document.querySelector('[data-step-panel="narrate"]')).toHaveAttribute("data-at", "bottom");
  });
});

describe("A prop picture that cannot load (#2688)", () => {
  it("gives way to the prop's emoji", async () => {
    const user = userEvent.setup();
    const story = propsOpener();
    story.art = { props: { snail: { sticker: "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data" } } };
    const { container } = renderPlayer(story);
    await user.click(next());
    const snail = container.querySelector('[data-prop="snail"]')!;
    const sticker = snail.querySelector("img")!;
    expect(sticker).not.toBeNull();
    act(() => {
      fireEvent.error(sticker);
    });
    expect(snail.querySelector("img")).toBeNull();
    expect(snail).toHaveTextContent("🐌");
  });

  it("does not make up a size for a course figure when saving data", () => {
    Object.defineProperty(navigator, "connection", { value: { saveData: true }, configurable: true });
    try {
      const prop: Prop = {
        id: "cells",
        label: { en: "onion cells", fr: "des cellules d'oignon" },
        query: "onion cells",
        kind: "figure",
        figure: { source_image_id: FIGURE_ID, figure_number: "Figure 1.4" },
      };
      render(
        <NextIntlClientProvider locale="fr" messages={frMessages}>
          <LookCloser
            variant="step"
            prop={prop}
            picture={pictureFor(prop, undefined, "fr")}
            target="fr"
            home="en"
            bilingual={false}
          />
        </NextIntlClientProvider>,
      );
      const button = screen.getByRole("button", { name: "Afficher la photo" });
      expect(within(button).queryByText(/Ko/)).toBeNull();
    } finally {
      // @ts-expect-error -- test cleanup of a stubbed property
      delete navigator.connection;
    }
  });
});
