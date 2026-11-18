/**
 * The cartoon stage (#2673) inside the story player: the cast on stage and
 * their pictures, the learner's choices at the start of a course's story
 * (#2672), the ways to move on, sound and read-aloud.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import type { StoryCourse } from "@/lib/story-course/types";

import { apiFetch } from "@/lib/api";
import { CHOICES_KEY_PREFIX, READ_ALOUD_KEY, SOUND_KEY } from "./stage/prefs";
import { resetSpeech } from "./stage/speech";
import { StoryPlayer, TITLE_BEAT_MS } from "./story-player";
import { cardReady, clickInCard } from "./story-test-utils";

// The stage draws a whole scene per step: long click-throughs need headroom
// on a busy CI runner.
vi.setConfig({ testTimeout: 20_000 });

// Read-aloud asks the server for AI clips (#2704). Offline by default here, so
// every line falls back to the browser's voice unless a test serves clips.
vi.mock("@/lib/api", () => ({ apiFetch: vi.fn(() => Promise.reject(new Error("offline"))) }));

afterEach(() => {
  resetSpeech();
  vi.mocked(apiFetch).mockReset();
  vi.mocked(apiFetch).mockImplementation(() => Promise.reject(new Error("offline")));
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
    await clickInCard(user, "La grenouille");
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
    await clickInCard(user, "Le caillou");
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "think");
    await clickInCard(user, "La grenouille");
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

    // The next story of the course opens straight away (its title first),
    // with the same friend.
    unmount();
    renderPlayer(contractStory());
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Suite" }));
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
    await clickInCard(user, "La grenouille");
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

describe("Stage — review fixes", () => {
  const next = () => screen.getByRole("button", { name: "Suite" });

  it("ignores a tap in the moment a question appears, then takes the answer", async () => {
    const user = userEvent.setup();
    const { onComplete } = renderPlayer(oldStory());
    for (let i = 0; i < 3; i += 1) await user.click(next());

    const card = document.querySelector('[data-step-panel="ask"]')!;
    expect(card).toHaveAttribute("data-armed", "false");
    // Not inert: a screen reader announces the question as it appears.
    expect(card).not.toHaveAttribute("inert");
    // The quick second tap of a double tap does not land on an answer.
    const wrong = screen.getByText("Le caillou").closest("button")!;
    await expect(user.click(wrong)).rejects.toThrow(/pointer-events/);
    expect(screen.getByRole("button", { name: "Réponds pour continuer" })).toBeDisabled();

    // Once the card is ready, a tap counts, and right first time scores 2.
    await cardReady();
    await user.click(screen.getByRole("button", { name: "La grenouille" }));
    await user.click(next());
    expect(onComplete).toHaveBeenCalledWith({ points: 2, maxPoints: 2 });
  });

  it("shows a chapter's title alone before a first line that would cover it", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.chapters[0].scenes[0].steps.shift(); // the chapter now opens on a speech bubble
    const { container } = renderPlayer(story);
    const dialogue = screen.getByTestId("story-stage").lastElementChild as HTMLElement;

    expect(container.querySelector("[data-title-card]")).not.toBeNull();
    // The first line is not there under the beat (#2682): nothing types out
    // unseen, and the live region that will announce it stays in the page.
    expect(dialogue).toBeEmptyDOMElement();
    expect(dialogue).toHaveAttribute("aria-live", "polite");
    expect(dialogue.style.visibility).toBe("");
    // Next ends the title's beat and brings up the first line, no further.
    await user.click(next());
    expect(container.querySelector("[data-title-card]")).toBeNull();
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
    await user.click(next());
    expect(screen.getByText("Elle a bougé !")).toBeInTheDocument();
  });

  it("never arms a question card under the title beat (#2682)", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.chapters[0].scenes[0].steps = [{ type: "ask", ref: "q1" }, ...story.chapters[0].scenes[0].steps];
    renderPlayer(story);
    expect(document.querySelector('[data-step-panel="ask"]')).toBeNull();
    // Long enough for a card mounted under the beat to have armed itself.
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(document.querySelector('[data-step-panel="ask"]')).toBeNull();
    await user.click(next());
    // It comes up with the first Next, and arms only now, in sight.
    expect(document.querySelector('[data-step-panel="ask"]')).toHaveAttribute("data-armed", "false");
    await cardReady();
  });

  it("fades the title card on its own", async () => {
    const story = oldStory();
    story.chapters[0].scenes[0].steps.shift();
    const { container } = renderPlayer(story);
    await waitFor(() => expect(container.querySelector("[data-title-card]")).toBeNull(), {
      timeout: TITLE_BEAT_MS + 2000,
    });
    expect(screen.getByText("Observe bien.")).toBeInTheDocument();
  });

  it("keeps the title over a narrator's caption, and never under a speech bubble", async () => {
    const user = userEvent.setup();
    const { container } = renderPlayer(oldStory());
    expect(container.querySelector("[data-title-card]")).not.toBeNull();
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
    await user.click(next());
    expect(container.querySelector("[data-title-card]")).toBeNull();
    expect(container.querySelector('[data-step-panel="say"]')).not.toBeNull();
  });

  it("leaves Space and → to the page when the story cannot move on", async () => {
    const user = userEvent.setup();
    renderPlayer(oldStory());
    // Moving on: the key is the story's.
    expect(fireEvent.keyDown(document.body, { key: "ArrowRight" })).toBe(false);
    for (let i = 0; i < 2; i += 1) await user.click(next());
    // A question waits: the key scrolls the page as usual.
    expect(fireEvent.keyDown(document.body, { key: " " })).toBe(true);
    expect(fireEvent.keyDown(document.body, { key: "ArrowRight" })).toBe(true);
  });

  it("hands the keyboard to the Next button after the start card", async () => {
    const user = userEvent.setup();
    renderPlayer(contractStory());
    await user.click(screen.getByRole("button", { name: /Jouer/ }));
    await waitFor(() => expect(next()).toHaveFocus());
  });

  it("says '1 étoile', not '1 étoiles'", async () => {
    const user = userEvent.setup();
    renderPlayer(oldStory());
    for (let i = 0; i < 3; i += 1) await user.click(next());
    await clickInCard(user, "Le caillou");
    await user.click(screen.getByRole("button", { name: "La grenouille" }));
    await user.click(next());
    expect(screen.getByText("1 étoile sur 3")).toBeInTheDocument();
  });

  it("hangs the chalkboard away from the teacher presenting it", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.chapters[0].scenes[0].steps.splice(1, 0, {
      type: "concept",
      title: { en: "Signs", fr: "Signes" },
      en: ["It moves."],
      fr: ["Il bouge."],
    });
    const { container } = renderPlayer(story);
    await user.click(next());
    // The teacher stands on the left: the board hangs on the right.
    expect(actor(container, "mentor")).toHaveAttribute("data-pose", "talk");
    expect(container.querySelector('[data-step-panel="concept"]')).toHaveAttribute("data-side", "right");
  });

  it("lays a timed game out under the stage at every width", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.chapters[0].scenes[0].steps.splice(1, 0, { type: "game", ref: "g1" });
    story.minigames = [
      {
        id: "g1",
        engine: "catch",
        title: { en: "Catch", fr: "Attrape" },
        instruction: { en: "Catch the living.", fr: "Attrape le vivant." },
        rounds: [{ items: [{ label: { en: "Frog", fr: "Grenouille" }, correct: true }] }],
      },
    ];
    renderPlayer(story);
    await user.click(next());
    const dialogue = screen.getByTestId("story-stage").lastElementChild as HTMLElement;
    expect(dialogue.className).toMatch(/dialogueFlow/);
  });

  it("swaps a speaker's picture in place, never remounting it", async () => {
    const user = userEvent.setup();
    const story = oldStory();
    story.art = {
      characters: { mentor: { idle: "/api/v1/story-art/k-idle/data", talk: "/api/v1/story-art/k-talk/data" } },
    };
    const { container } = renderPlayer(story);
    const picture = actor(container, "mentor")!.querySelector("img")!;
    await user.click(next());
    expect(actor(container, "mentor")!.querySelector("img")).toBe(picture);
    expect(picture).toHaveAttribute("src", "/api/v1/story-art/k-talk/data");
    await user.click(next());
    expect(actor(container, "mentor")!.querySelector("img")).toBe(picture);
  });

  it("fetches ahead only the poses of the cast on stage", () => {
    const fetched: string[] = [];
    class FakeImage {
      decoding = "";
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(url: string) {
        fetched.push(url);
      }
    }
    vi.stubGlobal("Image", FakeImage);
    const story = oldStory();
    story.chapters[0].scenes.push({
      id: "s2",
      place: "market",
      cast: ["margo"],
      steps: [{ type: "narrate", en: "Later.", fr: "Plus tard." }],
    });
    story.art = {
      characters: {
        mentor: { idle: "/a/pre-m-idle", talk: "/a/pre-m-talk", happy: "/a/pre-m-happy", think: "/a/pre-m-think" },
        // Not on stage in the first scene: Margo is only in the second.
        margo: { idle: "/a/pre-g-idle" },
      },
    };
    story.chapters[0].scenes[0].cast = ["mentor"];
    story.chapters[0].scenes[0].steps = story.chapters[0].scenes[0].steps.filter((step) => step.who !== "margo");
    renderPlayer(story);
    expect(fetched).toEqual(expect.arrayContaining(["/a/pre-m-idle", "/a/pre-m-talk", "/a/pre-m-happy", "/a/pre-m-think"]));
    expect(fetched).not.toContain("/a/pre-g-idle");
  });

  it("stands the stage still while the player is hidden", () => {
    renderPlayer(oldStory(), { active: false });
    expect(screen.getByTestId("story-stage").className).toMatch(/paused/);
  });

  it("draws the hero when a look's picture fails in the picker", () => {
    const story = contractStory();
    story.art = { characters: { "hero:girl": { idle: "/api/v1/story-art/gone/data" } } };
    renderPlayer(story);
    const choice = screen.getByRole("button", { name: /Une fille/ });
    fireEvent.error(choice.querySelector("img")!);
    expect(choice.querySelector("img")).toBeNull();
    expect(choice.querySelector("svg")).not.toBeNull();
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
    const played: string[] = [];
    class FakeAudio {
      src = "";
      preload = "";
      addEventListener() {}
      removeEventListener() {}
      pause() {}
      play() {
        played.push(this.src);
        return Promise.resolve();
      }
    }
    vi.stubGlobal("Audio", FakeAudio);
    return { speak, cancel, played };
  }

  /** The bodies of the read-aloud requests sent so far. */
  const clipRequests = () =>
    vi
      .mocked(apiFetch)
      .mock.calls.filter(([path]) => path === "/api/v1/story-audio")
      .map(([, init]) => JSON.parse(String(init?.body)));

  const readAloudToggle = () => screen.getByRole("button", { name: "Lire à voix haute" });
  const effectsToggle = () => screen.getByRole("button", { name: "Effets sonores" });

  it("does not read aloud until asked, so a screen reader is not spoken over", () => {
    const { speak } = stubSpeech();
    renderPlayer(oldStory());
    expect(speak).not.toHaveBeenCalled();
    expect(readAloudToggle()).toHaveAttribute("aria-pressed", "false");
    // Sound effects are a separate switch, on by default.
    expect(effectsToggle()).toHaveAttribute("aria-pressed", "true");
    // The dialogue announces each new line to a screen reader.
    expect(screen.getByTestId("story-stage").lastElementChild).toHaveAttribute("aria-live", "polite");
  });

  it("reads each line aloud once asked, in the target language and the speaker's voice", async () => {
    const user = userEvent.setup();
    const { speak } = stubSpeech();
    renderPlayer(oldStory());

    await user.click(readAloudToggle());
    expect(window.localStorage.getItem(READ_ALOUD_KEY)).toBe("on");
    // No AI clip (offline): the browser's voice reads the line.
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect(speak.mock.calls[0][0]).toMatchObject({ text: "Un mystère t'attend.", lang: "fr-FR" });
    // Read aloud, the screen reader does not announce the same line again.
    expect(screen.getByTestId("story-stage").lastElementChild).toHaveAttribute("aria-live", "off");

    await user.click(screen.getByRole("button", { name: "Suite" }));
    await waitFor(() =>
      expect(speak.mock.calls.at(-1)?.[0]).toMatchObject({ text: "Observe bien.", pitch: 0.8, rate: 0.9 }),
    );
  });

  it("reads each line with the AI voice, one per character, the next line asked for ahead (#2704)", async () => {
    const user = userEvent.setup();
    const { speak, played } = stubSpeech();
    vi.mocked(apiFetch).mockImplementation(async (_path, init) => {
      const body = JSON.parse(String(init?.body));
      return { id: "x", url: `/api/v1/story-audio/${encodeURIComponent(body.text)}/data` };
    });
    renderPlayer(oldStory());

    await user.click(readAloudToggle());
    await waitFor(() => expect(played).toContain(`/api/v1/story-audio/${encodeURIComponent("Un mystère t'attend.")}/data`));
    expect(clipRequests()).toEqual(
      expect.arrayContaining([
        { text: "Un mystère t'attend.", language: "fr", voice: "narrator" },
        // The next step's line, asked for while this one plays.
        expect.objectContaining({ text: "Observe bien.", language: "fr" }),
      ]),
    );
    const next = clipRequests().find((body) => body.text === "Observe bien.");
    expect(next.voice).not.toBe("narrator");
    expect(speak).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Suite" }));
    await waitFor(() => expect(played.at(-1)).toBe(`/api/v1/story-audio/${encodeURIComponent("Observe bien.")}/data`));
    // The prefetched clip is not asked for twice.
    expect(clipRequests().filter((body) => body.text === "Observe bien.")).toHaveLength(1);
    expect(speak).not.toHaveBeenCalled();
  });

  it("stops reading once switched off, and remembers both switches", async () => {
    const user = userEvent.setup();
    const { speak, cancel } = stubSpeech();
    window.localStorage.setItem(READ_ALOUD_KEY, "on");
    const { unmount } = renderPlayer(oldStory());
    await waitFor(() => expect(speak).toHaveBeenCalledTimes(1));
    expect(readAloudToggle().className).toMatch(/\bmin-h-11\b/);
    expect(effectsToggle().className).toMatch(/\bmin-h-11\b/);

    await user.click(readAloudToggle());
    expect(readAloudToggle()).toHaveAttribute("aria-pressed", "false");
    expect(cancel).toHaveBeenCalled();
    await user.click(effectsToggle());
    expect(effectsToggle()).toHaveAttribute("aria-pressed", "false");
    expect(window.localStorage.getItem(SOUND_KEY)).toBe("off");
    await user.click(screen.getByRole("button", { name: "Suite" }));
    expect(speak).toHaveBeenCalledTimes(1);

    unmount();
    renderPlayer(oldStory());
    expect(readAloudToggle()).toHaveAttribute("aria-pressed", "false");
    expect(effectsToggle()).toHaveAttribute("aria-pressed", "false");
  });

  it("does not read while out of sight", () => {
    const { speak } = stubSpeech();
    window.localStorage.setItem(READ_ALOUD_KEY, "on");
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
