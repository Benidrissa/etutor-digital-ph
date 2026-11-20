/**
 * Animation cues (#2739): what a step makes the stage do. A step may carry
 * `cues: [{ do, ...args }]`; the list is checked as a whole and folded forward
 * through the scene into one stage state per beat, so going back to a step
 * gives the same state. The whitelists mirror `story_course.py` (a test keeps
 * the two equal); stored data is untrusted, so any bad cue drops the whole
 * list of its step and that step plays as if it had none.
 */

import type { Mood, Prop, Step } from "@/lib/story-course/types";

import { slotsFor, type StageActor } from "./cast";
import type { Shot } from "./scene-plan";
import type { Sfx } from "./sound";

export const CUE_PRIMITIVES = [
  "enter", "exit", "move", "face", "costume", "show", "camera", "sound", "wait", "machine", "music",
] as const;
export const CUE_MARKS = ["left", "centre", "right", "off"] as const;
export const CUE_SOUNDS = ["pop", "whoosh", "correct", "oops", "coin", "fanfare", "star"] as const;
export const CUE_SHOTS = ["wide", "two", "close", "insert", "split"] as const;
export const CUE_POSES = ["idle", "talk", "happy", "think", "sad", "surprised", "walk"] as const;
export const MAX_CUES_PER_STEP = 8;
export const MAX_CUE_WAIT_MS = 2000;
/** At most this many props pointed at in one beat. */
export const MAX_BEAT_PROPS = 2;

/** An actor "off" stage stands this far beyond the edge (a % of the stage width). */
export const OFF_LEFT = -25;
export const OFF_RIGHT = 125;

type Cue = NonNullable<Step["cues"]>[number];
type Mark = (typeof CUE_MARKS)[number];

/** The stage state of one beat, for a scene that has cues. */
export interface BeatCues {
  /** Everyone mounted (those off stage included, so they can walk off), left to right as they came. */
  ids: string[];
  /** Where each stands, a % of the stage width, parallel to `ids`. */
  x: number[];
  /** Ids turned to face left. */
  flip: string[];
  /** Poses worn in this beat only. */
  costume: Record<string, Mood>;
  /** Sounds to play, `at` ms after the beat starts (after the waits before them). */
  sounds: { name: Sfx; at: number }[];
  /** Someone enters, exits or moves in this beat. */
  moving: boolean;
  /** When each entrance, exit or move of this beat starts, in ms after the beat (the waits before it). */
  delay: Record<string, number>;
  /** When each actor's first entrance started, in ms after its beat; kept to the end of the scene. */
  enterAt: Record<string, number>;
  /** When the idea machine of this beat's `show` starts, in ms after the beat (the waits before the cue); absent: when the step appears. */
  machineAt?: number;
  /** Camera shot of this beat; it wins over every automatic rule. */
  shot?: Shot;
}

const has = (list: readonly string[], value: unknown): value is string =>
  typeof value === "string" && list.includes(value);

/** The valid cues of a step, or null when it has none or any of them is bad. */
export function cuesOf(
  step: Step,
  actors: ReadonlyMap<string, StageActor>,
  props: ReadonlyMap<string, Prop>,
): Cue[] | null {
  const raw: unknown = (step as { cues?: unknown }).cues;
  if (!Array.isArray(raw) || !raw.length || raw.length > MAX_CUES_PER_STEP) return null;
  let wait = 0;
  const shown: unknown[] = Array.isArray(step.props) ? [...step.props] : [];
  // The validator only accepts actors of the scene (its cast and speakers) and
  // warns about the others; the player is more lenient and takes any actor of the story.
  const actor = (id: unknown) => typeof id === "string" && actors.has(id);
  for (const cue of raw as Record<string, unknown>[]) {
    if (!cue || typeof cue !== "object" || Array.isArray(cue)) return null;
    const ok = (() => {
      switch (cue.do) {
        case "enter":
          return actor(cue.who) && (cue.at === undefined || has(CUE_MARKS.slice(0, 3), cue.at));
        case "exit":
          return actor(cue.who);
        case "move":
          return actor(cue.who) && has(CUE_MARKS, cue.to);
        case "face":
          return actor(cue.who) && (has(CUE_MARKS, cue.toward) || actor(cue.toward));
        case "costume":
          return actor(cue.who) && has(CUE_POSES, cue.pose);
        case "show":
          shown.push(cue.prop);
          return typeof cue.prop === "string" && props.has(cue.prop);
        case "camera":
          return has(CUE_SHOTS, cue.shot);
        case "sound":
          return has(CUE_SOUNDS, cue.name);
        case "wait":
          wait += typeof cue.ms === "number" ? cue.ms : 0;
          return Number.isInteger(cue.ms) && (cue.ms as number) >= 1;
        case "machine":
          return step.type === "show" && !!step.visual;
        case "music":
          return true;
        default:
          return false;
      }
    })();
    if (!ok) return null;
  }
  if (wait > MAX_CUE_WAIT_MS || new Set(shown).size > MAX_BEAT_PROPS) return null;
  return raw as Cue[];
}

/** The prop ids a list points at with `show`. */
export function showsOf(cues: Cue[] | null): string[] {
  return (cues ?? []).flatMap((cue) => (cue.do === "show" && cue.prop ? [cue.prop] : []));
}

/**
 * Where a mark is, for `count` people standing on stage: the outer marks are
 * the end slots of `slotsFor`, the centre is the middle of the stage.
 */
export function markX(mark: Mark, count: number, from = 50): number {
  if (mark === "off") return from < 50 ? OFF_LEFT : OFF_RIGHT;
  const slots = slotsFor(Math.max(2, count));
  return mark === "left" ? slots[0] : mark === "right" ? slots[slots.length - 1] : 50;
}

const inView = (x: number) => x >= 0 && x <= 100;

/**
 * One state per step of a scene (null for a step without valid cues leaves the
 * state as it was). Position and facing hold until a later cue or the end of
 * the scene; costume, show, camera and sounds belong to their beat only.
 * A `wait` holds back the entrances, exits, moves, sounds and machine starts after it.
 * Whoever's first cue is `enter` starts the scene off stage; the others stand
 * at `slotsFor` of how many start on stage, and keep their place when others
 * arrive (an entrant may overlap them: the author picks the mark).
 */
export function foldCues(lists: (Cue[] | null)[], cast: string[]): BeatCues[] | null {
  if (!lists.some(Boolean)) return null;
  const first = new Map<string, string>();
  for (const cue of lists.flat()) {
    if (cue && cue.who && !first.has(cue.who)) first.set(cue.who, cue.do);
  }
  const start = cast.filter((id) => first.get(id) !== "enter");
  const ids = [...start];
  const x: Record<string, number> = {};
  const face: Record<string, boolean> = {};
  const enterAt: Record<string, number> = {};
  slotsFor(start.length).forEach((value, i) => (x[start[i]] = value));
  const standing = (skip?: string) => ids.filter((id) => id !== skip && inView(x[id])).length;
  const side = (id: string) => (x[id] < 50 ? OFF_LEFT : OFF_RIGHT);
  return lists.map((list) => {
    const beat: BeatCues = { ids: [], x: [], flip: [], costume: {}, sounds: [], moving: false, delay: {}, enterAt: {} };
    let elapsed = 0;
    for (const cue of list ?? []) {
      const who = cue.who as string;
      const onStage = ids.includes(who);
      switch (cue.do) {
        case "enter":
        case "move": {
          if (cue.do === "move" && !onStage) break;
          const mark = (cue.do === "enter" ? (cue.at ?? "centre") : cue.to) as Mark;
          if (!onStage) {
            ids.push(who);
            x[who] = OFF_RIGHT;
            enterAt[who] = elapsed;
          }
          x[who] = markX(mark, standing(who) + 1, x[who]);
          beat.delay[who] = elapsed;
          beat.moving = true;
          break;
        }
        case "exit":
          if (onStage) {
            x[who] = side(who);
            beat.delay[who] = elapsed;
          }
          beat.moving = true;
          break;
        case "face": {
          const target = cue.toward as string;
          const at = onStage ? x[who] : 0;
          const goal = has(CUE_MARKS, target)
            ? target === "off" ? side(who) : target === "centre" ? 50 : target === "left" ? 0 : 100
            : ids.includes(target) ? x[target] : at;
          if (onStage && goal !== at) face[who] = goal < at;
          break;
        }
        case "costume":
          if (onStage) beat.costume[who] = cue.pose as Mood;
          break;
        case "camera":
          beat.shot = cue.shot as Shot;
          break;
        case "sound":
          beat.sounds.push({ name: cue.name as Sfx, at: elapsed });
          break;
        case "machine":
          beat.machineAt = elapsed;
          break;
        case "wait":
          elapsed += cue.ms as number;
          break;
      }
    }
    beat.ids = [...ids];
    beat.x = ids.map((id) => x[id]);
    beat.flip = ids.filter((id) => face[id]);
    beat.enterAt = { ...enterAt };
    return beat;
  });
}

/** Cues need the Web Animations API; without it the scene plays as if no step had cues. */
export function canAnimate(): boolean {
  return typeof Element !== "undefined" && typeof Element.prototype.animate === "function";
}
