/**
 * The stage player's follow-ups (#2682) and its props (#2681 phase 1):
 * Previous, a hero look without art, the things the story talks about on
 * stage, their "look closely" close-ups and the image credits.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import type { StoryCourse } from "@/lib/story-course/types";

import { StoryPlayer } from "./story-player";
import { clickInCard } from "./story-test-utils";

vi.setConfig({ testTimeout: 20_000 });

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const SNAIL_PHOTO = "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data?size=s";
const SNAIL_PHOTO_LARGE = "/api/v1/story-props/9b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d/data?size=l";
const ONION_FIGURE_ID = "3f2c9a1e-0b7d-4c55-9e2a-1d2f3a4b5c6d";

/** Two chapters at two places, a question with an explanation, no props. */
function twoChapters(): StoryCourse {
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
        scenes: [
          {
            id: "s1",
            place: "classroom",
            steps: [
              { type: "narrate", en: "A mystery awaits.", fr: "Un mystère t'attend." },
              { type: "say", who: "mentor", en: "Look closely.", fr: "Observe bien." },
              { type: "ask", ref: "q1" },
            ],
          },
          {
            id: "s2",
            place: "school_yard",
            steps: [{ type: "say", who: "peer", en: "It moved!", fr: "Elle a bougé !" }],
          },
        ],
      },
      {
        id: "ch2",
        title: { en: "Cells", fr: "Les cellules" },
        scenes: [
          {
            id: "s3",
            place: "classroom",
            steps: [{ type: "narrate", en: "The next day.", fr: "Le lendemain." }],
          },
        ],
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
        ],
        explanation: { en: "A frog feeds and grows.", fr: "Une grenouille se nourrit et grandit." },
      },
    ],
    rewards: { unit: { en: "mangoes", fr: "mangues" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  };
}

/** The contract's example scene: a néré tree, a snail and a pebble. */
function propsStory(): StoryCourse {
  const story = twoChapters();
  story.cast = [
    { id: "hero", role: "hero", name: "Aminata", kind: "child", art: "hero" },
    { id: "friend", role: "friend", name: "Awa", kind: "child", art: "friend" },
  ];
  story.props = [
    { id: "pebble", label: { en: "a pebble", fr: "un caillou" }, query: "river pebble", kind: "sticker", emoji: "🪨", at: "ground", size: "s" },
    { id: "snail", label: { en: "a snail", fr: "un escargot" }, query: "garden snail", kind: "real", educational: true, emoji: "🐌", at: "ground", size: "s" },
    { id: "nere_tree", label: { en: "the néré tree", fr: "le néré" }, query: "Parkia biglobosa tree", kind: "real", emoji: "🌳", at: "back", size: "l" },
    {
      id: "onion_cells",
      label: { en: "onion skin cells", fr: "des cellules d'oignon" },
      query: "onion epidermis cells microscope",
      kind: "figure",
      educational: true,
      emoji: "🔬",
      at: "table",
      size: "s",
      figure: { source_image_id: ONION_FIGURE_ID, figure_number: "Figure 1.4", attribution: "OpenStax, CC BY 4.0" },
    },
  ];
  story.chapters = [
    {
      id: "c1",
      title: { en: "Alive or not", fr: "Vivant ou pas" },
      scenes: [
        {
          id: "c1s1",
          place: "school_yard",
          cast: ["hero", "friend"],
          props: ["nere_tree", "snail", "pebble"],
          steps: [
            {
              type: "narrate",
              en: "Under the néré tree, a snail crawls past a pebble.",
              fr: "Sous le néré, un escargot passe près d'un caillou.",
              props: ["nere_tree", "snail"],
            },
            { type: "show", visual: "prop", params: { prop: "snail" } },
            {
              type: "say",
              who: "hero",
              mood: "think",
              en: "A snail and a pebble… which one is alive?",
              fr: "Un escargot et un caillou… lequel est vivant ?",
              props: ["snail", "pebble"],
            },
            // Nothing to show for the pebble: this close-up is dropped.
            { type: "show", visual: "prop", params: { prop: "pebble" } },
            { type: "ask", ref: "q1" },
          ],
        },
      ],
    },
  ];
  story.art = {
    props_status: "partial",
    props: {
      snail: {
        picture: {
          src: SNAIL_PHOTO,
          src_large: SNAIL_PHOTO_LARGE,
          width: 400,
          height: 300,
          bytes: 21844,
          alt: { en: "a garden snail on a leaf", fr: "un escargot sur une feuille" },
          via: "open_photo",
          credit: {
            kind: "web",
            title: "Cornu aspersum 01",
            author: "Jane Doe",
            source: "Wikimedia Commons",
            license: "CC-BY-SA-4.0",
            license_url: "https://creativecommons.org/licenses/by-sa/4.0/",
            page_url: "https://commons.wikimedia.org/wiki/File:Cornu.jpg",
            attribution_required: true,
            text: {
              en: "\"Cornu aspersum 01\" by Jane Doe, CC BY-SA 4.0, via Wikimedia Commons",
              fr: "« Cornu aspersum 01 » par Jane Doe, CC BY-SA 4.0, via Wikimedia Commons",
            },
          },
        },
      },
    },
  };
  return story;
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
const prop = (container: HTMLElement, id: string) => container.querySelector(`[data-prop="${id}"]`);

describe("Previous (#2682)", () => {
  it("sits next to Next, and does nothing on the first line", () => {
    renderPlayer(twoChapters());
    expect(previous()).toBeDisabled();
    expect(previous().parentElement).toBe(next().parentElement);
  });

  it("goes back one line at a time, across scenes and chapters", async () => {
    const user = userEvent.setup();
    renderPlayer(twoChapters(), { variant: "page" });
    await user.click(next());
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    await user.click(next());
    await clickInCard(user, "La grenouille");
    await user.click(next());
    expect(screen.getByText("Elle a bougé !")).toBeInTheDocument();
    await user.click(next());
    // Chapter 2 opens on a caption: its title shows with it, no beat.
    expect(screen.getByText("Le lendemain.")).toBeInTheDocument();

    await user.click(previous());
    expect(screen.getByText("Elle a bougé !")).toBeInTheDocument();
    await user.click(previous());
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();
    await user.click(previous());
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    await user.click(previous());
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
    expect(previous()).toBeDisabled();
  });

  it("shows an answered question with the learner's answer and the explanation, never scoring it again", async () => {
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(twoChapters(), { chapterId: "ch1", maxPoints: 2 });
    await user.click(next());
    await user.click(next());
    // Wrong, then right on the second try: 1 mango.
    await clickInCard(user, "Le caillou");
    await clickInCard(user, "La grenouille");
    expect(screen.getByText("+1 mangues")).toBeInTheDocument();
    await user.click(next());
    expect(screen.getByText("Elle a bougé !")).toBeInTheDocument();

    await user.click(previous());
    const card = document.querySelector('[data-step-panel="ask"]')!;
    // Nothing to arm: it is settled, read-only.
    expect(card).toHaveAttribute("data-armed", "true");
    expect(within(card as HTMLElement).getByRole("button", { name: /La grenouille/ })).toBeDisabled();
    expect(within(card as HTMLElement).getByRole("button", { name: /Le caillou/ })).toBeDisabled();
    expect(within(card as HTMLElement).getByText(/Ta réponse/)).toBeInTheDocument();
    expect(within(card as HTMLElement).getByText("Une grenouille se nourrit et grandit.")).toBeInTheDocument();
    // The story can move on straight away, and the score is the same.
    expect(next()).toBeEnabled();
    expect(screen.getByText("1")).toBeInTheDocument();

    await user.click(next());
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete).toHaveBeenCalledWith({ points: 1, maxPoints: 2 });
  });

  it("shows a line seen again at once, with no typing and no title beat", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(twoChapters());
    await user.click(next());
    await user.click(previous());
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
    expect(container.querySelector("[data-typing]")).toBeNull();
    await user.click(next());
    expect(container.querySelector("[data-typing]")).toBeNull();
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
  });

  it("never goes back to the start card", async () => {
    const user = userEvent.setup();
    const story = twoChapters();
    story.cast = [
      { id: "hero", role: "hero", name: "Aminata", kind: "child", art: "hero", variants: [{ id: "girl" }, { id: "boy" }] },
      ...story.cast,
    ];
    renderPlayer(story);
    expect(screen.queryByRole("button", { name: "Précédent" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Jouer/ }));
    expect(previous()).toBeDisabled();
    await user.click(next());
    await user.click(previous());
    expect(screen.queryByRole("button", { name: /Jouer/ })).not.toBeInTheDocument();
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
  });

  it("goes back with ← and with a swipe to the right on the stage", async () => {
    const user = userEvent.setup();
    renderPlayer(twoChapters());
    await user.click(next());
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();

    await user.click(next());
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    fireEvent.touchStart(stageBox(), { touches: [{ clientX: 40, clientY: 100 }] });
    fireEvent.touchEnd(stageBox(), { changedTouches: [{ clientX: 160, clientY: 110 }] });
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();

    // A swipe that is mostly up or down is a scroll, not "back".
    await user.click(next());
    fireEvent.touchStart(stageBox(), { touches: [{ clientX: 40, clientY: 100 }] });
    fireEvent.touchEnd(stageBox(), { changedTouches: [{ clientX: 140, clientY: 220 }] });
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
  });
});

describe("A hero look without art (#2682)", () => {
  it("never keeps the other look's picture", () => {
    const story = twoChapters();
    story.cast = [
      { id: "hero", role: "hero", name: "Aminata", kind: "child", art: "hero", variants: [{ id: "girl" }, { id: "boy" }] },
      ...story.cast,
    ];
    story.chapters[0].scenes[0].cast = ["hero", "mentor"];
    story.art = { characters: { "hero:girl": { idle: "/api/v1/story-art/girl-idle/data" } } };
    const { container } = renderPlayer(story);
    const hero = () => container.querySelector('[data-actor="hero"]')!;

    const picture = hero().querySelector("img")!;
    expect(picture).toHaveAttribute("src", "/api/v1/story-art/girl-idle/data");
    fireEvent.load(picture);
    // The boy has no art yet: the drawn figure, not the girl's picture.
    fireEvent.click(screen.getByRole("button", { name: /Un garçon/ }));
    expect(hero().querySelector("img")).toBeNull();
    expect(hero().querySelector("svg")).not.toBeNull();
  });
});

describe("Props on stage (#2681)", () => {
  it("brings the scenery in with the scene and pops in what the line names", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(propsStory());
    // Props pop in with their line, never under the chapter's title.
    expect(container.querySelector("[data-prop]")).toBeNull();
    await user.click(next());

    expect(prop(container, "nere_tree")).not.toBeNull();
    expect(prop(container, "snail")).toHaveAttribute("data-entering", "true");
    expect(prop(container, "snail")).toHaveAttribute("data-pointed", "true");
    // The pebble waits for the line that names it.
    expect(prop(container, "pebble")).toBeNull();
    // Props stand in front of the cast: on a wide stage the caption goes up.
    expect(document.querySelector('[data-step-panel="narrate"]')).toHaveAttribute("data-at", "top");
    // Drawn as their emoji while no sticker exists.
    expect(prop(container, "nere_tree")).toHaveTextContent("🌳");
  });

  it("closes up on the real thing, with its credit", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(propsStory());
    await user.click(next());
    await user.click(next());

    const look = document.querySelector('[data-step-panel="look"]') as HTMLElement;
    expect(within(look).getByText("Regarde de près")).toBeInTheDocument();
    expect(within(look).getByRole("heading", { name: /un escargot/ })).toBeInTheDocument();
    const photo = within(look).getByRole("img", { name: "un escargot sur une feuille" });
    expect(photo).toHaveAttribute("src", SNAIL_PHOTO);
    expect(photo.getAttribute("srcset")).toContain(`${SNAIL_PHOTO_LARGE} 960w`);
    expect(within(look).getByText(/Cornu aspersum 01/)).toBeInTheDocument();
    expect(within(look).getByRole("link", { name: "CC BY-SA 4.0" })).toHaveAttribute(
      "href",
      "https://creativecommons.org/licenses/by-sa/4.0/",
    );
    // The hero is amazed.
    expect(container.querySelector('[data-actor="hero"]')).toHaveAttribute("data-pose", "surprised");
  });

  it("bounces a prop named again, pops the new one, and drops a close-up with nothing to show", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(propsStory());
    await user.click(next());
    await user.click(next());
    await user.click(next());

    expect(prop(container, "snail")).toHaveAttribute("data-pointed", "true");
    expect(prop(container, "snail")).not.toHaveAttribute("data-entering");
    expect(prop(container, "pebble")).toHaveAttribute("data-entering", "true");
    expect(prop(container, "pebble")).toHaveTextContent("🪨");

    // The pebble's close-up had no picture and no sticker: straight to the question.
    await user.click(next());
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();
    expect(screen.queryByText("Regarde de près")).not.toBeInTheDocument();
  });

  it("opens a prop's close-up from the stage, and gives the focus back on Esc", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(propsStory());
    await user.click(next());

    // Only a prop with a picture is a button; the others are decoration.
    expect(prop(container, "nere_tree")!.tagName).toBe("SPAN");
    const snail = screen.getByRole("button", { name: "Regarde de près : un escargot" });
    await user.click(snail);
    const dialog = screen.getByRole("dialog", { name: "Regarde de près : un escargot" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(within(dialog).getByRole("button", { name: "Retour à l'histoire" })).toHaveFocus();
    // The story does not move on behind it.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("Sous le néré, un escargot passe près d'un caillou.")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(snail).toHaveFocus());
  });

  it("lists every picture's credit, built from the story alone", async () => {
    const user = userEvent.setup();
    renderPlayer(propsStory());
    await user.click(screen.getByRole("button", { name: "Crédits images" }));
    const sheet = screen.getByRole("dialog", { name: "Crédits images" });
    expect(within(sheet).getByText("des cellules d'oignon")).toBeInTheDocument();
    expect(within(sheet).getByText("Tiré du cours · Figure 1.4 · OpenStax, CC BY 4.0")).toBeInTheDocument();
    expect(within(sheet).getByText("un escargot")).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: "Source" })).toHaveAttribute(
      "href",
      "https://commons.wikimedia.org/wiki/File:Cornu.jpg",
    );
    // Course figures come first.
    const items = within(sheet).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Figure 1.4");
    await user.click(within(sheet).getByRole("button", { name: "Retour à l'histoire" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("has no credits button when the story shows no picture", () => {
    renderPlayer(twoChapters());
    expect(screen.queryByRole("button", { name: "Crédits images" })).not.toBeInTheDocument();
  });
});
