/** The balance, cycle and cause-chain machines (#2756) as the learner sees them. */

import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import { isMachineVisual } from "@/lib/story-course/machines";
import type { Chapter, StoryCourse } from "@/lib/story-course/types";

import fixture from "../../../backend/tests/fixtures/story_machines_2756.json";
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

const label = (en: string, fr = en) => ({ en, fr });
const BALANCE = { left: { label: label("Costs", "Coûts"), value: 1200 }, right: { label: label("Income", "Recettes"), value: 950 }, highlight: "left" };
const CYCLE = { stages: [label("Evaporation", "Évaporation"), label("Condensation"), label("Rain", "Pluie"), label("Run-off", "Ruissellement")], start: 2, highlight: "stage3" };
const CHAIN = { links: [label("Less rain", "Moins de pluie"), label("Dry well", "Puits à sec"), label("Poor harvest", "Mauvaise récolte")], highlight: "link2" };

const parts = (c: HTMLElement) => [...c.querySelectorAll("[data-part]")].map((g) => g.getAttribute("data-part"));
const angle = (c: HTMLElement) => Number(c.querySelector("[data-angle]")?.getAttribute("data-angle"));
const marker = (c: HTMLElement) => Number(c.querySelector("[data-marker]")?.getAttribute("data-marker"));
const lit = (c: HTMLElement) => [...c.querySelectorAll("[data-lit]")].map((g) => g.getAttribute("data-lit") === "true");

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

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

describe("balance", () => {
  it("names its parts, outlines the highlighted one and describes itself", async () => {
    const { container } = renderVisual({ visual: "balance", params: BALANCE, play: false });
    await screen.findByRole("group", { name: "Scale comparing Costs (1,200) with Income (950). The heavier side is Costs." });
    await vi.waitFor(() => expect(parts(container)).toEqual(["beam", "left", "right"]));
    expect(container.querySelectorAll("[data-highlighted]")).toHaveLength(1);
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe("left");
    expect(container.textContent).toContain("1,200");
  });

  it("describes itself in French and shows the French labels", async () => {
    const { container } = renderVisual({ visual: "balance", params: BALANCE }, "fr");
    await screen.findByRole("group", { name: "Balance comparant Coûts (1 200) et Recettes (950). Le côté le plus lourd : Coûts." });
    await vi.waitFor(() => expect(container.textContent).toContain("Recettes"));
  });

  it("waits for its start, then tilts toward the larger value", async () => {
    const view = renderVisual({ visual: "balance", params: BALANCE, play: false });
    await vi.waitFor(() => expect(angle(view.container)).toBe(0));
    await new Promise((done) => setTimeout(done, 600));
    expect(angle(view.container)).toBe(0);
    view.rerender(
      <NextIntlClientProvider locale="en" messages={enMessages}>
        <ConceptVisual visual="balance" params={BALANCE} language="en" play />
      </NextIntlClientProvider>,
    );
    await vi.waitFor(() => expect(angle(view.container)).toBeLessThan(0), { timeout: 5000 });
  });

  it("stays level for equal values", async () => {
    const equal = { ...BALANCE, right: { ...BALANCE.right, value: 1200 } };
    const { container } = renderVisual({ visual: "balance", params: equal, reveal: true });
    await screen.findByRole("group", { name: /balanced/ });
    expect(angle(container)).toBe(0);
  });
});

describe("cycle", () => {
  it("names its stages, outlines one and describes itself", async () => {
    const { container } = renderVisual({ visual: "cycle", params: CYCLE, play: false });
    await screen.findByRole("group", { name: "Cycle of 4 stages: Evaporation, Condensation, Rain, Run-off, then back to Condensation." });
    await vi.waitFor(() => expect(parts(container)).toEqual(["stage1", "stage2", "stage3", "stage4"]));
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe("stage3");
  });

  it("describes itself in French", async () => {
    renderVisual({ visual: "cycle", params: CYCLE }, "fr");
    await screen.findByRole("group", { name: "Cycle de 4 étapes : Évaporation, Condensation, Pluie, Ruissellement, puis retour à Condensation." });
  });

  it("starts the marker at start, then goes round to it again", async () => {
    const { container } = renderVisual({ visual: "cycle", params: CYCLE, play: true });
    await vi.waitFor(() => expect(marker(container)).toBe(1));
    await vi.waitFor(() => expect(marker(container)).toBe(2), { timeout: 5000 });
  });
});

describe("cause_chain", () => {
  it("names its links, outlines one and describes itself", async () => {
    const { container } = renderVisual({ visual: "cause_chain", params: CHAIN, play: false });
    await screen.findByRole("group", { name: "Chain of 3 causes, each leading to the next: Less rain, Dry well, Poor harvest." });
    await vi.waitFor(() => expect(parts(container)).toEqual(["link1", "link2", "link3"]));
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe("link2");
    expect(lit(container)).toEqual([false, false, false]);
  });

  it("lights the links in order once started", async () => {
    const { container } = renderVisual({ visual: "cause_chain", params: CHAIN, play: true });
    await vi.waitFor(() => expect(lit(container)).toEqual([true, false, false]), { timeout: 5000 });
    await vi.waitFor(() => expect(lit(container)).toEqual([true, true, true]), { timeout: 5000 });
  });

  it("wraps a 40-character label inside the box", async () => {
    const long = { links: [label("x".repeat(40)), label("A fairly long cause of forty characters!!".slice(0, 40))] };
    const { container } = renderVisual({ visual: "cause_chain", params: long, reveal: true });
    await vi.waitFor(() => expect(parts(container)).toHaveLength(2));
    for (const line of container.querySelectorAll("tspan")) expect((line.textContent ?? "").length).toBeLessThanOrEqual(19);
  });
});

describe("reduced motion", () => {
  it("steps the balance by a button of 44 px", async () => {
    reduceMotion();
    const { container } = renderVisual({ visual: "balance", params: BALANCE, play: true });
    const next = await screen.findByRole("button", { name: "Next step" });
    expect(next.className).toContain("min-h-11");
    expect(angle(container)).toBe(0);
    fireEvent.click(next);
    expect(angle(container)).toBeLessThan(0);
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });

  it("steps the marker round the ring, then stops", async () => {
    reduceMotion();
    const { container } = renderVisual({ visual: "cycle", params: CYCLE, play: true });
    const next = await screen.findByRole("button", { name: "Next step" });
    const seen = [marker(container)];
    for (let i = 0; i < 4; i++) {
      fireEvent.click(screen.getByRole("button", { name: "Next step" }));
      seen.push(marker(container));
    }
    expect(seen).toEqual([1, 2, 3, 0, 1]);
    expect(next.isConnected).toBe(false);
  });

  it("lights one more link at each press, and has the button in French", async () => {
    reduceMotion();
    const { container } = renderVisual({ visual: "cause_chain", params: CHAIN, play: true }, "fr");
    fireEvent.click(await screen.findByRole("button", { name: "Étape suivante" }));
    expect(lit(container)).toEqual([true, false, false]);
  });

  it("shows the end at once when revealed, with no button", async () => {
    reduceMotion();
    const { container } = renderVisual({ visual: "cause_chain", params: CHAIN, reveal: true });
    await vi.waitFor(() => expect(lit(container)).toEqual([true, true, true]));
    expect(screen.queryByRole("button", { name: "Next step" })).toBeNull();
  });
});

describe("params that cannot be drawn", () => {
  it.each([
    ["balance", {}],
    ["balance", { ...BALANCE, highlight: "mark" }],
    ["balance", { ...BALANCE, left: { label: label("x"), value: -1 } }],
    ["cycle", { stages: [label("a"), label("b")] }],
    ["cycle", { stages: CYCLE.stages, start: 5 }],
    ["cycle", { stages: "rain" }],
    ["cause_chain", { links: [label("a")] }],
    ["cause_chain", { links: CHAIN.links, highlight: "link9" }],
    ["cause_chain", null],
  ])("%s %j shows the unavailable box and does not throw", (visual, params) => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    renderVisual({ visual, params: params as never });
    expect(screen.getByText("This picture is not available yet.")).toBeTruthy();
    expect(screen.queryByRole("img")).toBeNull();
  });
});

describe("the fixture story (#2756)", () => {
  const course = fixture as unknown as StoryCourse;
  const chapters = course.chapters as Chapter[];
  const beats = planSteps(chapters, chapters, buildActors(course, undefined), { props: new Map() }).filter(
    (p) => p.sceneId === "machines-ideas",
  );
  const shows = beats.filter((p) => p.step.type === "show");

  it("holds the three machines, each started by the machine cue", () => {
    expect(shows.map((p) => p.step.visual)).toEqual(["balance", "cycle", "cause_chain"]);
    for (const p of shows) expect(isMachineVisual(p.step.visual)).toBe(true);
    expect(shows.map((p) => p.cues?.machineAt)).toEqual([0, 400, 0]);
  });

  it.each([0, 1, 2])("draws show step %i with its highlight", async (at) => {
    const step = shows[at].step;
    const { container } = renderVisual({ visual: step.visual!, params: step.params, reveal: true });
    await vi.waitFor(() => expect(container.querySelectorAll("[data-part]").length).toBeGreaterThan(0));
    expect(container.querySelector("[data-highlighted]")?.getAttribute("data-part")).toBe(String(step.params?.highlight));
  });
});
