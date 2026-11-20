/** The idea machines (#2740) as the learner sees them, and when they start. */

import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { Chapter, StoryCourse } from "@/lib/story-course/types";

import machines from "../../../backend/tests/fixtures/story_machines_2740.json";
import { ConceptVisual } from "./concept-visual";
import { buildActors } from "./stage/cast";
import { planSteps } from "./stage/scene-plan";

vi.setConfig({ testTimeout: 20_000 });

function renderVisual(props: React.ComponentProps<typeof ConceptVisual>, locale: "fr" | "en" = "en") {
  return render(
    <NextIntlClientProvider locale={locale} messages={locale === "fr" ? frMessages : enMessages}>
      <ConceptVisual language={locale} {...props} />
    </NextIntlClientProvider>,
  );
}

const placed = (container: HTMLElement) =>
  [...container.querySelectorAll("[data-dropped]")].map((g) => g.getAttribute("data-dropped") === "true");
const ball = (container: HTMLElement) => Number(container.querySelector("[data-ball]")?.getAttribute("data-ball"));
const BIG = { n: 4305892176, reveal: "groups", highlight: "millions" };

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("place_value", () => {
  it("names its groups, outlines the highlighted one and describes itself", async () => {
    const { container } = renderVisual({ visual: "place_value", params: BIG, play: false });
    await screen.findByRole("group", { name: "4,305,892,176: 4 billion, 305 million, 892 thousand, 176" });
    await vi.waitFor(() => expect(container.querySelectorAll("[data-part]")).toHaveLength(4));
    expect([...container.querySelectorAll("[data-part]")].map((g) => g.getAttribute("data-part"))).toEqual([
      "billions",
      "millions",
      "thousands",
      "ones",
    ]);
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe("millions");
    expect(container.querySelectorAll("[data-highlighted]")).toHaveLength(1);
  });

  it("describes itself in French", async () => {
    renderVisual({ visual: "place_value", params: { n: 2000000 } }, "fr");
    await screen.findByRole("group", { name: "2 000 000 : 2 millions" });
  });

  it("waits for its start, then drops the groups by itself", async () => {
    const view = renderVisual({ visual: "place_value", params: BIG, play: false });
    await screen.findByRole("group");
    await vi.waitFor(() => expect(placed(view.container)).toHaveLength(4));
    await new Promise((done) => setTimeout(done, 1000));
    expect(placed(view.container)).toEqual([false, false, false, false]);
    view.rerender(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ConceptVisual visual="place_value" params={BIG} language="en" play />
      </NextIntlClientProvider>,
    );
    await vi.waitFor(() => expect(placed(view.container)).toEqual([true, true, true, true]), { timeout: 5000 });
  });

  it("shows the end state at once when revealed", async () => {
    const { container } = renderVisual({ visual: "place_value", params: BIG, play: false, reveal: true });
    await vi.waitFor(() => expect(placed(container)).toEqual([true, true, true, true]));
  });
});

describe("number_line", () => {
  const LINE = { from: 0, to: 100, mark: 40, step: 10, highlight: "mark" };

  it("names from, to and mark, outlines the mark and describes itself", async () => {
    const { container } = renderVisual({ visual: "number_line", params: LINE, play: false });
    await screen.findByRole("group", { name: "Number line from 0 to 100. The ball stops at 40." });
    await vi.waitFor(() => expect(container.querySelectorAll("[data-part]")).toHaveLength(3));
    expect([...container.querySelectorAll("[data-part]")].map((g) => g.getAttribute("data-part"))).toEqual([
      "from",
      "to",
      "mark",
    ]);
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe("mark");
  });

  it("rolls the ball to the mark once started", async () => {
    const { container } = renderVisual({ visual: "number_line", params: LINE, play: true });
    await vi.waitFor(() => expect(ball(container)).toBe(0));
    await vi.waitFor(() => expect(ball(container)).toBe(40), { timeout: 5000 });
  });
});

describe("reduced motion", () => {
  function reduceMotion() {
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

  it("shows stills stepped by a button of 44 px", async () => {
    reduceMotion();
    const { container } = renderVisual({ visual: "place_value", params: { n: 4305892 }, play: true });
    const next = await screen.findByRole("button", { name: "Next step" });
    expect(next.className).toContain("min-h-11");
    expect(placed(container)).toEqual([false, false, false]);
    fireEvent.click(next);
    expect(placed(container)).toEqual([false, false, true]);
    fireEvent.click(next);
    fireEvent.click(next);
    expect(placed(container)).toEqual([true, true, true]);
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });

  it("steps the ball by the button and shows the end when revealed", async () => {
    reduceMotion();
    const params = { from: 0, to: 8, mark: 8 };
    const { container, unmount } = renderVisual({ visual: "number_line", params, play: true });
    fireEvent.click(await screen.findByRole("button", { name: "Next step" }));
    expect(ball(container)).toBe(2);
    unmount();
    const end = renderVisual({ visual: "number_line", params, play: true, reveal: true });
    await vi.waitFor(() => expect(ball(end.container)).toBe(8));
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });

  it("has its button in French", async () => {
    reduceMotion();
    renderVisual({ visual: "place_value", params: { n: 5000 } }, "fr");
    await screen.findByRole("button", { name: "Étape suivante" });
  });
});

describe("params that cannot be drawn", () => {
  it.each([
    ["place_value", { n: -4 }],
    ["place_value", { n: 10 ** 12 }],
    ["place_value", {}],
    ["number_line", { from: 5, to: 1 }],
    ["number_line", { from: 0, to: 10, mark: 99 }],
    ["number_line", { from: 0, to: 10, highlight: "mark" }],
  ])("%s %j shows the unavailable box and does not throw", (visual, params) => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    renderVisual({ visual, params });
    expect(screen.getByText("This picture is not available yet.")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("the machine cue (#2739) in the plan", () => {
  const course = machines as unknown as StoryCourse;
  const chapters = course.chapters as Chapter[];
  const beats = planSteps(chapters, chapters, buildActors(course, undefined), { props: new Map() }).filter(
    (p) => p.sceneId === "machines",
  );
  const of = (visual: string) => beats.find((p) => p.step.type === "show" && p.step.visual === visual);

  it("starts the machine when the cue plays, after the wait before it", () => {
    expect(of("place_value")?.cues?.machineAt).toBe(400);
  });

  it("leaves a machine without the cue to start when its step appears", () => {
    const line = of("number_line");
    expect(line?.cues).toBeDefined();
    expect(line?.cues?.machineAt).toBeUndefined();
  });
});
