/** The camera shots (#2712): the heuristic and the mood mark. */

import { describe, expect, it } from "vitest";

import type { Step, StoryArt } from "@/lib/story-course/types";

import { moodMarkFor } from "./cast";
import { sceneShotOf, shotFor } from "./scene-plan";

const plan = (step: Step, extra: { startsScene?: boolean; pointed?: string[] } = {}) => ({
  step,
  startsScene: false,
  pointed: [],
  ...extra,
});

describe("shotFor", () => {
  it("opens a scene wide, on a line that shows the place ribbon", () => {
    expect(shotFor(plan({ type: "narrate", en: "x" }, { startsScene: true }))).toBe("wide");
    expect(shotFor(plan({ type: "say", who: "a", mood: "talk", en: "x" }, { startsScene: true }))).toBe("wide");
    expect(shotFor(plan({ type: "narrate", en: "x" }))).toBeUndefined();
  });

  it("plays every show step as an insert, with or without a picture", () => {
    expect(shotFor(plan({ type: "show", visual: "prop", params: { prop: "p" } }))).toBe("insert");
    expect(shotFor(plan({ type: "show", visual: "hundred_square" }))).toBe("insert");
  });

  it("splits a compare", () => {
    expect(shotFor(plan({ type: "show", visual: "compare" }))).toBe("split");
  });

  it("closes in on a surprised or think line that points at a prop", () => {
    const say = (mood: Step["mood"]) => ({ type: "say" as const, who: "a", mood, en: "x" });
    expect(shotFor(plan(say("surprised"), { pointed: ["p"] }))).toBe("close");
    expect(shotFor(plan(say("think"), { pointed: ["p"] }))).toBe("close");
    expect(shotFor(plan(say("surprised")))).toBeUndefined();
    expect(shotFor(plan(say("happy"), { pointed: ["p"] }))).toBeUndefined();
  });

  it("frames a two-shot on the line that leads into a question", () => {
    const line: Step = { type: "say", who: "a", mood: "talk", en: "x" };
    expect(shotFor(plan(line), { type: "ask", ref: "q" })).toBe("two");
    expect(shotFor(plan(line), { type: "narrate", en: "y" })).toBeUndefined();
  });

  it("lets a step's own shot override, and ignores an unknown one", () => {
    const base = { type: "say", who: "a", en: "x" } as const;
    expect(shotFor(plan({ ...base, shot: "split" }, { startsScene: true }))).toBe("split");
    expect(shotFor(plan({ ...base, shot: "bogus" } as unknown as Step, { startsScene: true }))).toBe("wide");
  });
});

describe("moodMarkFor", () => {
  const art = (poses: Record<string, string>) =>
    ({ characters: { hero: poses } }) as unknown as StoryArt;
  it("marks a surprised or sad pose the art lacks, when another picture stands in", () => {
    const a = art({ idle: "/i.png", happy: "/h.png" });
    expect(moodMarkFor(a, "hero", "surprised")).toBe("surprised");
    expect(moodMarkFor(a, "hero", "sad")).toBe("sad");
  });
  it("marks nothing for drawn art poses, real art of the mood, or no art at all", () => {
    const a = art({ idle: "/i.png", surprised: "/s.png" });
    expect(moodMarkFor(a, "hero", "surprised")).toBeUndefined();
    expect(moodMarkFor(a, "hero", "happy")).toBeUndefined();
    // Stock art with both new poses (#2741): the picture is served, no badge.
    const both = art({ idle: "/i.png", surprised: "/s.png", sad: "/d.png" });
    expect(moodMarkFor(both, "hero", "sad")).toBeUndefined();
    expect(moodMarkFor(both, "hero", "surprised")).toBeUndefined();
    expect(moodMarkFor(undefined, "hero", "sad")).toBeUndefined();
    expect(moodMarkFor(art({}), "hero", "sad")).toBeUndefined();
  });
});

describe("sceneShotOf", () => {
  it("keeps the scene still during an insert: only the picture in its panel moves", () => {
    expect(sceneShotOf("insert")).toBeUndefined();
  });

  it("passes every other shot to the scene's layers", () => {
    expect(sceneShotOf("wide")).toBe("wide");
    expect(sceneShotOf("close")).toBe("close");
    expect(sceneShotOf("two")).toBe("two");
    expect(sceneShotOf("split")).toBe("split");
    expect(sceneShotOf(undefined)).toBeUndefined();
  });
});
