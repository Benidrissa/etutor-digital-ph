/**
 * The cartoon stage (#2673) inside the story player: the cast on stage and
 * their pictures, the learner's choices at the start of a course's story
 * (#2672), the ways to move on, sound and read-aloud.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import type { StoryCourse } from "@/lib/story-course/types";

import { CHOICES_KEY_PREFIX, SOUND_KEY } from "./stage/prefs";
import { StoryPlayer } from "./story-player";

// The stage draws a whole scene per step: long click-throughs need headroom
// on a busy CI runner.
vi.setConfig({ testTimeout: 20_000 });

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

/** A module story written before the contract: cast mentor, peer and margo. */
function oldStory(): StoryCourse {
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
      { id: "margo", name: "Margo", kind: "ai_tutor", art: "margo", voice: { pitch: 1.8, rate: 1.05 } },
      { id: "mentor", name: "M. Kaboré", kind: "adult", art: "mr_kabore", voice: { pitch: 0.8, rate: 0.9 } },
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
              { type: "say", who: "mentor", mood: "talk", en: "Look closely.", fr: "Observe bien." },
              { type: "say", who: "peer", mood: "happy", en: "It moved!", fr: "Elle a bougé !" },
              { type: "ask", ref: "q1" },
              { type: "say", who: "margo", en: "Well done.", fr: "Bravo." },
            ],
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
          { id: "b", en: "The stone", fr: "Le caillou", misconception: "m1" },
        ],
      },
    ],
    rewards: { unit: { en: "points", fr: "points" }, first_try: 2, second_try: 1 },
    checks: { max_points: 2 },
  };
}

/** A story written to the contract: a hero to pick and a friend to name. */
function contractStory(): StoryCourse {
  const story = oldStory();
  story.course = "Sciences 6e";
  story.learner = { first_name: "Aminata" };
  story.cast = [
    {
      id: "hero",
      role: "hero",
      name: "Aminata",
      kind: "child",
      art: "hero",
      variants: [{ id: "girl" }, { id: "boy" }],
    },
    { id: "friend", role: "friend", name: "{friend}", default_name: "Awa", kind: "child", art: "friend" },
    { id: "mentor", role: "mentor", name: "M. Kaboré", kind: "adult", art: "mr_kabore" },
  ];
  story.chapters[0].scenes[0].cast = ["hero", "friend", "mentor"];
  story.chapters[0].scenes[0].steps = [
    { type: "say", who: "friend", mood: "happy", en: "Hi, I am {friend}!", fr: "Salut, c'est {friend} !" },
    { type: "say", who: "hero", en: "Let's go.", fr: "On y va." },
  ];
  story.questions = [];
  story.checks = { max_points: 0 };
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

function actor(container: HTMLElement, id: string): HTMLElement | null {
  return container.querySelector(`[data-actor="${id}"]`);
}

/** The stage itself (backdrop and cast), where a tap moves the story on. */
function stageBox(): HTMLElement {
  return screen.getByTestId("story-stage").firstElementChild as HTMLElement;
}

/** Reduced motion: no typing effect, so the story moves on at the first tap. */
function preferReducedMotion() {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("reduce"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

describe("Stage — the cast", () => {
  it("puts the older cast on stage, drawn as placeholders", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(oldStory());

    // Everyone who speaks in the scene stands on stage; the tutor on the right.
    const ids = [...container.querySelectorAll("[data-actor]")].map((el) => el.getAttribute("data-actor"));
    expect(ids).toEqual(["mentor", "peer", "margo"]);
    expect(actor(container, "mentor")?.querySelector("svg")).not.toBeNull();
    expect(actor(container, "mentor")?.querySelector("img")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Suite" }));
    // The speaker talks; the others stand by.
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "talk");
    expect(actor(container, "peer")).toHaveAttribute("data-pose", "idle");
    expect(screen.getByText("M. Kaboré")).toBeInTheDocument();
    expect(screen.getByText("Observe bien.")).toHaveAttribute("lang", "fr");
  });

  it("labels Margo as the AI tutor in her speech bubble", async () => {
    const user = userEvent.setup();
    renderPlayer(oldStory());
    for (let i = 0; i < 3; i += 1) await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "La grenouille" }));
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByText("Margo (IA)")).toBeInTheDocument();
  });

  it("shows generated art for the pose, and a placeholder where there is none", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.art = {
      status: "partial",
      characters: { mentor: { idle: "/api/v1/story-art/m-idle/data", talk: "/api/v1/story-art/m-talk/data" } },
      places: { classroom: "/api/v1/story-art/classroom/data" },
    };
    const { container } = renderPlayer(story);

    expect(actor(container, "mentor")?.querySelector("img")).toHaveAttribute("src", "/api/v1/story-art/m-idle/data");
    // No art for the peer: the drawn placeholder.
    expect(actor(container, "peer")?.querySelector("img")).toBeNull();
    expect(container.querySelector('img[src="/api/v1/story-art/classroom/data"]')).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(actor(container, "mentor")?.querySelector("img")).toHaveAttribute("src", "/api/v1/story-art/m-talk/data");
  });

  it("falls back to the placeholder when a picture fails to load", () => {
    const story = oldStory();
    story.art = { characters: { mentor: { idle: "/api/v1/story-art/gone/data" } } };
    const { container } = renderPlayer(story);
    fireEvent.error(actor(container, "mentor")!.querySelector("img")!);
    expect(actor(container, "mentor")?.querySelector("img")).toBeNull();
    expect(actor(container, "mentor")?.querySelector("svg")).not.toBeNull();
  });

  it("never puts an unsafe art URL in the page", () => {
    const story = oldStory();
    story.art = { characters: { mentor: { idle: "javascript:alert(1)" } }, places: { classroom: "//evil.example/x.png" } };
    const { container } = renderPlayer(story);
    expect(container.querySelector("img")).toBeNull();
  });

  it("lets the reacting character think over a wrong answer and cheer a right one", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(oldStory());
    for (let i = 0; i < 3; i += 1) await user.click(screen.getByRole("button", { name: "Suite" }));

    // No hero in this cast: the first one on stage reacts.
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "think");
    await user.click(screen.getByRole("button", { name: "Le caillou" }));
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "think");
    await user.click(screen.getByRole("button", { name: "La grenouille" }));
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "happy");
  });
});

describe("Stage — the learner's choices", () => {
  it("asks for the friend's name and the hero once, then fills {friend} in", async () => {
    const user = userEvent.setup();
    const { container, unmount } = renderPlayer(contractStory());

    // Nothing plays before the learner starts.
    expect(screen.queryByRole("button", { name: "Suite" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Salut, c'est/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Un garçon/ }));
    // The hero on stage already wears the chosen look.
    expect(screen.getByRole("button", { name: /Un garçon/ })).toHaveAttribute("aria-pressed", "true");
    await user.type(screen.getByRole("textbox", { name: /meilleur ami/ }), "Fatou");
    await user.click(screen.getByRole("button", { name: /Jouer/ }));

    expect(screen.getByText("Salut, c'est Fatou !")).toBeInTheDocument();
    expect(within(container).getByText("Fatou")).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(`${CHOICES_KEY_PREFIX}Sciences 6e`)!)).toEqual({
      friend: "Fatou",
      variant: "boy",
    });

    // The next story of the course opens straight away, with the same friend.
    unmount();
    renderPlayer(contractStory());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Salut, c'est Fatou !")).toBeInTheDocument();
  });

  it("uses the cast's default name when the learner types none", async () => {
    const user = userEvent.setup();
    renderPlayer(contractStory());
    expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", "Awa");
    await user.click(screen.getByRole("button", { name: /Jouer/ }));
    expect(screen.getByText("Salut, c'est Awa !")).toBeInTheDocument();
  });

  it("still starts when storage is unavailable", async () => {
    const user = userEvent.setup();
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    renderPlayer(contractStory());
    await user.type(screen.getByRole("textbox"), "Kofi");
    await user.click(screen.getByRole("button", { name: /Jouer/ }));
    expect(screen.getByText("Salut, c'est Kofi !")).toBeInTheDocument();
  });

  it("asks nothing of a story with no friend to name and no hero to pick", () => {
    renderPlayer(oldStory());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
  });
});

describe("Stage — moving on", () => {
  it("moves on with → and Space, but not past an unanswered question", async () => {
    const user = userEvent.setup();
    renderPlayer(oldStory());

    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    await user.keyboard(" ");
    expect(screen.getByText("Elle a bougé !")).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();

    await user.keyboard("{ArrowRight}");
    await user.keyboard(" ");
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Réponds pour continuer" })).toBeDisabled();
  });

  it("moves on with a tap on the stage, but not while a question waits", async () => {
    preferReducedMotion();
    const user = userEvent.setup();
    renderPlayer(oldStory());

    await user.click(stageBox());
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    await user.click(stageBox());
    await user.click(stageBox());
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();
    await user.click(stageBox());
    expect(screen.getByText("Lequel est vivant ?")).toBeInTheDocument();
  });

  it("finishes the line being typed before a tap moves on", async () => {
    const user = userEvent.setup();
    renderPlayer(oldStory());
    await user.click(stageBox());
    // The first tap only showed the rest of the line.
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
    await user.click(stageBox());
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
  });

  it("cheers at the end even when the parent shows the summary", async () => {
    const user = userEvent.setup();
    const { container, onComplete } = renderPlayer(oldStory(), { hideFinishSummary: true, maxPoints: 2 });
    for (let i = 0; i < 3; i += 1) await user.click(screen.getByRole("button", { name: "Suite" }));
    await user.click(screen.getByRole("button", { name: "La grenouille" }));
    await user.click(screen.getByRole("button", { name: "Suite" }));

    expect(onComplete).toHaveBeenCalledWith({ points: 2, maxPoints: 2 });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    // Everyone jumps for joy; the stars are drawn on the stage.
    for (const el of container.querySelectorAll("[data-actor]")) {
      expect(el).toHaveAttribute("data-pose", "happy");
    }
    expect(screen.getByText("Bravo !")).toBeInTheDocument();
  });
});

describe("Stage — sound", () => {
  function stubSpeech() {
    const speak = vi.fn();
    const cancel = vi.fn();
    class Utterance {
      text: string;
      lang = "";
      pitch = 1;
      rate = 1;
      voice: unknown = null;
      constructor(text: string) {
        this.text = text;
      }
    }
    vi.stubGlobal("speechSynthesis", { speak, cancel, getVoices: () => [] });
    vi.stubGlobal("SpeechSynthesisUtterance", Utterance);
    return { speak, cancel };
  }

  it("reads each line aloud, in the target language and the speaker's voice", async () => {
    const user = userEvent.setup();
    const { speak } = stubSpeech();
    renderPlayer(oldStory());

    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0][0]).toMatchObject({ text: "Un mystère t'attend.", lang: "fr-FR" });

    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(speak.mock.calls.at(-1)?.[0]).toMatchObject({ text: "Observe bien.", pitch: 0.8, rate: 0.9 });
  });

  it("stops reading and stays quiet once muted, and remembers it", async () => {
    const user = userEvent.setup();
    const { speak, cancel } = stubSpeech();
    const { unmount } = renderPlayer(oldStory());
    const toggle = screen.getByRole("button", { name: "Lecture à voix haute et effets sonores" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle.className).toMatch(/\bmin-h-11\b/);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(cancel).toHaveBeenCalled();
    expect(window.localStorage.getItem(SOUND_KEY)).toBe("off");
    const spoken = speak.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(speak).toHaveBeenCalledTimes(spoken);

    unmount();
    renderPlayer(oldStory());
    expect(screen.getByRole("button", { name: "Lecture à voix haute et effets sonores" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("does not read while out of sight", () => {
    const { speak } = stubSpeech();
    renderPlayer(oldStory(), { active: false });
    expect(speak).not.toHaveBeenCalled();
  });

  it("plays without speech synthesis at all", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("speechSynthesis", undefined);
    renderPlayer(oldStory());
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
  });
});
