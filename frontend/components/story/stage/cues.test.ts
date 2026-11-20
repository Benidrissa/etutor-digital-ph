/** Animation cues (#2739): validation, the fold through a scene, the plan. */

import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import type { Chapter, Prop, Step, StoryCourse } from "@/lib/story-course/types";

import { buildActors, slotsFor } from "./cast";
import {
  CUE_MARKS,
  CUE_POSES,
  MAX_BEAT_PROPS,
  CUE_PRIMITIVES,
  CUE_SHOTS,
  CUE_SOUNDS,
  MAX_CUES_PER_STEP,
  MAX_CUE_WAIT_MS,
  OFF_LEFT,
  OFF_RIGHT,
  canAnimate,
  cuesOf,
  markX,
} from "./cues";
import { planSteps } from "./scene-plan";
import fixture from "../../../../backend/tests/fixtures/story_cues_2739.json";
import w04 from "../../../../backend/tests/fixtures/story_course_w04.json";

const course = fixture as unknown as StoryCourse;
const actors = buildActors(course, undefined);
const props = new Map<string, Prop>((course.props ?? []).map((prop) => [prop.id, prop]));
const context = { props };
const chapters = course.chapters as Chapter[];

/** The cue scene of the fixture, planned. */
const cueBeats = () => planSteps(chapters, chapters, actors, context).filter((p) => p.sceneId === "cues");

const say = (cues: unknown, extra: Partial<Step> = {}) =>
  ({ type: "say", who: "nandi", en: "x", fr: "x", cues, ...extra }) as unknown as Step;
const check = (cues: unknown, extra: Partial<Step> = {}) => cuesOf(say(cues, extra), actors, props);

describe("cue whitelists mirror the backend", () => {
  const python = readFileSync(
    path.resolve(process.cwd(), "..", "backend/app/api/v1/schemas/story_course.py"),
    "utf8",
  );
  const tuple = (name: string) => {
    const body = new RegExp(`^${name} = \\(([^)]*)\\)`, "m").exec(python)?.[1] ?? "";
    return [...body.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  };
  const number = (name: string) => Number(new RegExp(`^${name} = (\\d+)`, "m").exec(python)?.[1]);

  it("has the same primitives, marks, sounds, shots and limits", () => {
    expect(tuple("CUE_PRIMITIVES")).toEqual([...CUE_PRIMITIVES]);
    expect(tuple("CUE_MARKS")).toEqual([...CUE_MARKS]);
    expect(tuple("CUE_SOUNDS")).toEqual([...CUE_SOUNDS]);
    expect(tuple("CUE_SHOTS")).toEqual([...CUE_SHOTS]);
    expect(tuple("MOODS")).toEqual([...CUE_POSES]);
    expect(number("MAX_PROPS_PER_LINE")).toBe(MAX_BEAT_PROPS);
    expect(number("MAX_CUES_PER_STEP")).toBe(MAX_CUES_PER_STEP);
    expect(number("MAX_CUE_WAIT_MS")).toBe(MAX_CUE_WAIT_MS);
  });
});

describe("validation", () => {
  it("accepts every primitive", () => {
    const good: unknown[] = [
      { do: "enter", who: "nandi" },
      { do: "enter", who: "nandi", at: "right" },
      { do: "exit", who: "papa" },
      { do: "move", who: "nandi", to: "off" },
      { do: "face", who: "nandi", toward: "papa" },
      { do: "face", who: "nandi", toward: "left" },
      { do: "costume", who: "nandi", pose: "sad" },
      { do: "show", prop: "cash_register" },
      { do: "camera", shot: "close" },
      { do: "sound", name: "coin" },
      { do: "wait", ms: 2000 },
      { do: "music", track: "anything" },
    ];
    for (const cue of good) expect(check([cue]), JSON.stringify(cue)).toHaveLength(1);
    expect(check([{ do: "machine" }], { type: "show", visual: "division_ladder" })).toHaveLength(1);
  });

  it("drops the whole list on any bad cue", () => {
    const ok = { do: "sound", name: "pop" };
    const bad: unknown[] = [
      { do: "dance" },
      { do: "enter" },
      { do: "enter", who: "ghost" },
      { do: "enter", who: "nandi", at: "off" },
      { do: "move", who: "nandi" },
      { do: "move", who: "nandi", to: "up" },
      { do: "face", who: "nandi", toward: "ghost" },
      { do: "costume", who: "nandi", pose: "angry" },
      { do: "show", prop: "unknown_prop" },
      { do: "camera", shot: "zoom" },
      { do: "sound", name: "boom" },
      { do: "wait", ms: 0 },
      { do: "wait", ms: -5 },
      { do: "wait", ms: 1.5 },
      { do: "wait", ms: "300" },
      { do: "wait", ms: true },
      { do: "machine" },
      "enter",
      null,
      [],
    ];
    for (const cue of bad) expect(check([ok, cue]), JSON.stringify(cue)).toBeNull();
    expect(check("enter")).toBeNull();
    expect(check({ do: "sound", name: "pop" })).toBeNull();
    expect(check([])).toBeNull();
    expect(check(undefined)).toBeNull();
  });

  it("holds the limits at their boundary", () => {
    const pop = { do: "sound", name: "pop" };
    expect(check(Array(MAX_CUES_PER_STEP).fill(pop))).toHaveLength(MAX_CUES_PER_STEP);
    expect(check(Array(MAX_CUES_PER_STEP + 1).fill(pop))).toBeNull();
    expect(check([{ do: "wait", ms: 1000 }, { do: "wait", ms: 1000 }])).not.toBeNull();
    expect(check([{ do: "wait", ms: 1000 }, { do: "wait", ms: 1001 }])).toBeNull();
  });

  it("allows two props in a beat, counting the step's own", () => {
    const two = new Map(props).set("b", props.get("cash_register")!).set("c", props.get("cash_register")!);
    const own = say([{ do: "show", prop: "b" }, { do: "show", prop: "c" }], { props: ["cash_register"] });
    expect(cuesOf(own, actors, two)).toBeNull();
    expect(cuesOf(say([{ do: "show", prop: "b" }], { props: ["cash_register"] }), actors, two)).not.toBeNull();
  });

  it("allows machine only on a show step with a visual", () => {
    expect(check([{ do: "machine" }], { type: "show" })).toBeNull();
    expect(check([{ do: "machine" }], { type: "show", visual: "x" })).not.toBeNull();
  });
});

describe("marks", () => {
  it("come from slotsFor for the heads on stage; off is beyond the edge", () => {
    expect(markX("left", 2)).toBe(slotsFor(2)[0]);
    expect(markX("right", 2)).toBe(slotsFor(2)[1]);
    expect(markX("left", 3)).toBe(15);
    expect(markX("centre", 3)).toBe(50);
    expect(markX("right", 3)).toBe(85);
    expect(markX("right", 5)).toBe(slotsFor(5)[4]);
    expect(markX("left", 1)).toBe(17);
    expect(markX("off", 3, 20)).toBe(OFF_LEFT);
    expect(markX("off", 3, 80)).toBe(OFF_RIGHT);
  });
});

describe("the fixture, played through planSteps", () => {
  const beats = cueBeats();

  it("walks nandi on, then papa; the narrator's scene starts with kabore alone", () => {
    expect(beats).toHaveLength(5);
    expect(beats[0].cues).toMatchObject({ ids: ["kabore", "nandi"], x: [18, 50] });
    expect(beats[0].cues?.moving).toBe(true);
    expect(beats[1].cues).toMatchObject({ ids: ["kabore", "nandi", "papa"], x: [18, 50, 85] });
    // The scene's own cast and the intro are untouched.
    expect(beats[1].cast).toEqual(["nandi", "papa", "kabore"]);
  });

  it("plays sounds in order, after the waits before them", () => {
    expect(beats[0].cues?.sounds).toEqual([{ name: "pop", at: 0 }]);
    expect(beats[4].cues?.sounds).toEqual([{ name: "star", at: 0 }]);
    const wait = cuesOf(say([{ do: "wait", ms: 300 }, { do: "sound", name: "coin" }]), actors, props);
    expect(wait).toHaveLength(2);
  });

  it("gives the costume and camera shot to their beat only", () => {
    expect(beats[1].cues?.costume).toEqual({ papa: "surprised" });
    expect(beats[2].cues?.costume).toEqual({});
    expect(beats[1].shot).toBe("two");
    expect(beats[1].pointed).toEqual(["cash_register"]);
    expect(beats[2].shot).not.toBe("two");
    expect(beats[2].pointed).toEqual([]);
  });

  it("moves nandi to the left and kabore to the centre, then sends papa off; positions hold", () => {
    expect(beats[2].cues?.x).toEqual([50, 15, 85]);
    expect(beats[3].cues?.x).toEqual([50, 15, 85]);
    expect(beats[4].cues?.x).toEqual([50, 15, OFF_RIGHT]);
  });

  it("never leaves two actors on one mark", () => {
    for (const beat of beats) {
      const onStage = beat.cues!.x.filter((x) => x >= 0 && x <= 100);
      expect(new Set(onStage).size).toBe(onStage.length);
      onStage.sort((a, b) => a - b).forEach((x, i) => i && expect(x - onStage[i - 1]).toBeGreaterThanOrEqual(25));
    }
  });

  it("holds a move back by the waits before it, in its beat only", () => {
    expect(beats[2].cues?.delay).toEqual({ nandi: 0, kabore: 300 });
    expect(beats[3].cues?.delay).toEqual({});
    expect(beats[4].cues?.delay).toEqual({ papa: 0 });
    const late = JSON.parse(JSON.stringify(chapters)) as Chapter[];
    const steps = late[0].scenes!.find((scene) => scene.id === "cues")!.steps!;
    steps[1].cues = [{ do: "wait", ms: 400 }, { do: "enter", who: "papa", at: "right" }];
    const plan = planSteps(late, late, actors, context).filter((p) => p.sceneId === "cues");
    // The entrance keeps its moment for the rest of the scene, so it never plays twice.
    expect(plan[0].cues?.enterAt).toEqual({ nandi: 0 });
    expect(plan.slice(1).map((p) => p.cues?.enterAt)).toEqual(Array(4).fill({ nandi: 0, papa: 400 }));
  });

  it("gives the same state when a beat is planned again (going back)", () => {
    expect(cueBeats().map((p) => p.cues)).toEqual(beats.map((p) => p.cues));
  });

  it("turns toward another actor or a mark", () => {
    const turned: Chapter[] = JSON.parse(JSON.stringify(chapters));
    const steps = turned[0].scenes!.find((scene) => scene.id === "cues")!.steps!;
    steps[3].cues = [{ do: "face", who: "papa", toward: "nandi" }, { do: "face", who: "kabore", toward: "left" }];
    const plan = planSteps(turned, turned, actors, context).filter((p) => p.sceneId === "cues");
    expect(plan[3].cues?.flip).toEqual(["kabore", "papa"]);
    expect(plan[4].cues?.flip).toEqual(["kabore", "papa"]);
    expect(plan[2].cues?.flip).toEqual([]);
  });

  it("does not drop the scene's other steps when one list is bad", () => {
    const broken: Chapter[] = JSON.parse(JSON.stringify(chapters));
    const steps = broken[0].scenes!.find((scene) => scene.id === "cues")!.steps!;
    steps[1].cues = [{ do: "enter", who: "ghost" }];
    const plan = planSteps(broken, broken, actors, context).filter((p) => p.sceneId === "cues");
    expect(plan[1].shot).not.toBe("two");
    expect(plan[1].cues?.ids).toEqual(plan[0].cues?.ids);
    // Papa's first valid cue is the exit, so he stands from the start.
    expect(plan[2].cues?.ids).toEqual(["papa", "kabore", "nandi"]);
    expect(plan[2].cues?.x[2]).toBe(markX("left", 3));
  });
});

describe("a story without cues plays as before", () => {
  const strip = (list: Chapter[]): Chapter[] => {
    const copy: Chapter[] = JSON.parse(JSON.stringify(list));
    for (const chapter of copy) for (const scene of chapter.scenes ?? []) for (const s of scene.steps ?? []) delete s.cues;
    return copy;
  };

  const bare = (list: ReturnType<typeof planSteps>) => list.map((p) => ({ ...p, step: { ...p.step, cues: undefined } }));

  it("adds no key and no change to a cue-free plan", () => {
    const plain = strip(chapters);
    const plan = planSteps(plain, plain, actors, context);
    expect(plan.some((p) => "cues" in p)).toBe(false);
    expect(bare(plan)).toEqual(bare(planSteps(chapters, chapters, actors, context, { cues: false })));
  });

  it("treats the cue-free scenes of a cue story as before", () => {
    const withCues = planSteps(chapters, chapters, actors, context);
    const without = planSteps(strip(chapters), strip(chapters), actors, context);
    const others = (list: typeof withCues) => list.filter((p) => p.sceneId !== "cues");
    expect(bare(others(withCues))).toEqual(bare(others(without)));
  });

  it("is identical for a stored story", () => {
    const stored = w04 as unknown as StoryCourse;
    const storedActors = buildActors(stored, undefined);
    const storedChapters = stored.chapters as Chapter[];
    const plan = planSteps(storedChapters, storedChapters, storedActors);
    expect(plan.some((p) => "cues" in p)).toBe(false);
    expect(plan).toEqual(planSteps(storedChapters, storedChapters, storedActors, undefined, { cues: false }));
  });

  it("ignores every cue when the browser cannot animate", () => {
    const plan = planSteps(chapters, chapters, actors, context, { cues: false });
    expect(plan.some((p) => "cues" in p)).toBe(false);
    expect(plan.find((p) => p.sceneId === "cues")?.shot).not.toBe("two");
    // jsdom has no Web Animations API.
    expect(canAnimate()).toBe(false);
  });
});
