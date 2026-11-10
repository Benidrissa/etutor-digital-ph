/**
 * What the player brings into view after each step (#2692), and how Previous
 * hands the keyboard back without scrolling the page itself.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import frMessages from "@/messages/fr.json";
import type { StoryCourse } from "@/lib/story-course/types";

import { StoryPlayer } from "./story-player";

const revealMock = vi.hoisted(() => vi.fn());
vi.mock("./stage/scroll", () => ({ reveal: revealMock }));

vi.setConfig({ testTimeout: 20_000 });

afterEach(() => {
  revealMock.mockReset();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

function story(): StoryCourse {
  return {
    format: "story-course/1",
    id: "week-x-fr",
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
              { type: "narrate", en: "The frog jumps.", fr: "La grenouille saute." },
              { type: "say", who: "mentor", en: "Look closely.", fr: "Observe bien." },
            ],
          },
        ],
      },
    ],
    questions: [],
    rewards: { unit: { en: "mangoes", fr: "mangues" }, first_try: 2, second_try: 1 },
    checks: { max_points: 0 },
  } as StoryCourse;
}

function renderPlayer(variant: "page" | "embedded" = "embedded") {
  return render(
    <NextIntlClientProvider locale="fr" messages={frMessages}>
      <StoryPlayer course={story()} variant={variant} />
    </NextIntlClientProvider>,
  );
}

/** The step's dialogue box: on a wide stage it lies over the whole stage. */
const dialogue = () => screen.getByTestId("story-stage").lastElementChild as HTMLElement;

/** As if the stage were wide: the dialogue box is positioned over it. */
function wideStage() {
  const real = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element, pseudo) => {
    const style = real(element, pseudo);
    if (element === dialogue()) return { ...style, position: "absolute" } as CSSStyleDeclaration;
    return style;
  });
}

async function flushFrames() {
  await act(async () => {
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
}

describe("What comes into view after a step (#2692)", () => {
  it("on a wide stage, is the step's own panel (the caption), not the whole stage", async () => {
    const user = userEvent.setup();
    renderPlayer("page");
    wideStage();
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await flushFrames();
    const target = revealMock.mock.calls.at(-1)?.[0] as HTMLElement;
    expect(target).not.toBe(dialogue());
    expect(target).toHaveAttribute("data-step-panel", "narrate");
  });

  it("under the stage (a phone), is the dialogue box, at its laid-out size", async () => {
    const user = userEvent.setup();
    renderPlayer("embedded");
    await user.click(screen.getByRole("button", { name: "Suite" }));
    await flushFrames();
    const [target, options] = revealMock.mock.calls.at(-1) ?? [];
    expect(target).toBe(dialogue());
    // Embedded, down to the Next button's place under it; the controls,
    // which stick to the foot of a tablet or laptop screen, are not a bar.
    const { to, ignore } = options as { to?: HTMLElement; ignore?: HTMLElement };
    expect(to?.contains(screen.getByRole("button", { name: "Suite" }))).toBe(true);
    expect(ignore).toBe(to);
  });
});

describe("Previous hands the keyboard back without scrolling (#2692)", () => {
  it("leaves the focus on the page after a swipe that started there", async () => {
    const user = userEvent.setup();
    renderPlayer();
    await user.click(screen.getByRole("button", { name: "Suite" }));
    (document.activeElement as HTMLElement | null)?.blur();
    const stage = screen.getByTestId("story-stage").firstElementChild as HTMLElement;
    fireEvent.touchStart(stage, { touches: [{ clientX: 40, clientY: 100 }] });
    fireEvent.touchEnd(stage, { changedTouches: [{ clientX: 160, clientY: 105 }] });
    await flushFrames();
    expect(screen.getByText("Un mystère t'attend.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suite" })).not.toHaveFocus();
  });

  it("moves it from a disabled Previous to Next, without scrolling the page", async () => {
    const user = userEvent.setup();
    renderPlayer();
    await user.click(screen.getByRole("button", { name: "Suite" }));
    const next = screen.getByRole("button", { name: "Suite" });
    const focus = vi.spyOn(next, "focus");
    screen.getByRole("button", { name: "Précédent" }).focus();
    await user.keyboard("{Enter}");
    await flushFrames();
    expect(next).toHaveFocus();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
  });
});
