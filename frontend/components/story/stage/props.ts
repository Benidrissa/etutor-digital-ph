/**
 * Props (#2681): the concrete things a story talks about — a snail, a pebble,
 * the néré tree — shown on the stage while the lines name them, and for real
 * in a "look closely" close-up.
 *
 * Pure logic, unit-tested: where a prop stands, how big it is, which props
 * are on stage at each step (popping in on a first mention, bouncing on the
 * next ones), what token draws it (sticker, polaroid, emoji, name tag) and
 * what picture its close-up shows. Phase 1 has no image spend at all: every
 * prop is visible as its emoji or its name.
 */

import { text } from "@/lib/story-course/answer";
import type {
  Prop,
  PropMedia,
  PropPicture,
  PropPlacement,
  PropSize,
  Step,
  TextObject,
} from "@/lib/story-course/types";

import { GROUND } from "./cast";

/** Height of a prop as a share of the stage height, per size. */
export const PROP_HEIGHT: Record<PropSize, number> = { s: 15, m: 22, l: 64 };

/** At most this many props in front of the cast, and one piece of scenery. */
export const MAX_FOREGROUND = 2;
export const MAX_SCENERY = 1;

/** A table's top, as a share of the stage height above the ground line. */
const TABLE_HEIGHT = 9;
/** Never shrink a prop below this to fit between the cast. */
const MIN_SCALE = 0.7;

const PLACEMENTS: ReadonlySet<string> = new Set(["ground", "table", "held", "sky", "back"]);

export function isScenery(placement: PropPlacement): boolean {
  return placement === "back" || placement === "sky";
}

/** Where a prop stands; a held prop whose holder is not on stage is put down. */
export function placementOf(prop: Prop, castOnStage: readonly string[] = []): PropPlacement {
  const at = prop.at && PLACEMENTS.has(prop.at) ? prop.at : "ground";
  if (at === "held" && (!prop.holder || !castOnStage.includes(prop.holder))) return "ground";
  return at;
}

/** A prop's size: held props are small, and only scenery may be large. */
export function sizeOf(prop: Prop, placement: PropPlacement): PropSize {
  if (placement === "held") return "s";
  const wanted: PropSize | undefined =
    prop.size === "s" || prop.size === "m" || prop.size === "l" ? prop.size : undefined;
  if (wanted === "l" && placement !== "back") return "m";
  if (wanted) return wanted;
  if (placement === "sky") return "s";
  if (placement === "back") return "l";
  return "m";
}

/* -------------------------------------------------------------------------- */
/* Layout                                                                      */
/* -------------------------------------------------------------------------- */

/** Where someone stands: slot and figure height, in % of the stage. */
export interface StandingFigure {
  id: string;
  x: number;
  height: number;
}

export interface PropSlot {
  /** Centre, as a % of the stage width. */
  x: number;
  /** Bottom edge, as a % of the stage height. */
  bottom: number;
  /** As a % of the stage height (after any scaling). */
  height: number;
  /** 1 behind the cast, 2 beside them, 3 in front of their feet, 4 in a hand. */
  z: number;
  onTable: boolean;
}

/** A figure's (or a square prop's) width as a share of the stage width (4:3 stage). */
function widthOf(height: number, aspect = 130 / 240): number {
  return height * aspect * 0.75;
}

interface Gap {
  from: number;
  to: number;
}

/** The free stretches of the floor between the cast's bodies. */
function freeGaps(standing: readonly StandingFigure[]): Gap[] {
  const taken = standing
    .map((figure) => {
      const half = widthOf(figure.height) / 2;
      return { from: figure.x - half, to: figure.x + half };
    })
    .sort((a, b) => a.from - b.from);
  const gaps: Gap[] = [];
  let cursor = 3;
  for (const body of taken) {
    if (body.from > cursor) gaps.push({ from: cursor, to: body.from });
    cursor = Math.max(cursor, body.to);
  }
  if (cursor < 97) gaps.push({ from: cursor, to: 97 });
  return gaps;
}

export interface OnStageProp {
  prop: Prop;
  placement: PropPlacement;
  size: PropSize;
}

/**
 * Where each prop on stage goes: scenery behind the cast, held props in a
 * hand, the rest on the floor in the widest free stretches between the cast
 * (shrunk to fit, never below 70%, else in front of their feet).
 */
export function layoutProps(
  onStage: readonly OnStageProp[],
  standing: readonly StandingFigure[],
): Map<string, PropSlot> {
  const slots = new Map<string, PropSlot>();

  // Scenery: behind the cast, between them where possible.
  for (const item of onStage.filter((entry) => isScenery(entry.placement))) {
    const height = PROP_HEIGHT[item.size];
    if (item.placement === "sky") {
      slots.set(item.prop.id, { x: 78, bottom: 70, height, z: 1, onTable: false });
      continue;
    }
    const xs = [...standing].map((figure) => figure.x).sort((a, b) => a - b);
    const x = xs.length === 0 ? 50 : xs.length === 1 ? (xs[0] < 50 ? 70 : 30) : xs.length === 2 ? 50 : (xs[0] + xs[1]) / 2;
    slots.set(item.prop.id, { x, bottom: GROUND + 4, height, z: 1, onTable: false });
  }

  // Held: in the holder's hand.
  for (const item of onStage.filter((entry) => entry.placement === "held")) {
    const holder = standing.find((figure) => figure.id === item.prop.holder);
    if (!holder) continue;
    const side = holder.x <= 50 ? 1 : -1;
    slots.set(item.prop.id, {
      x: holder.x + side * widthOf(holder.height) * 0.42,
      bottom: GROUND + holder.height * 0.3,
      height: PROP_HEIGHT.s,
      z: 4,
      onTable: false,
    });
  }

  // On the floor or a table: the widest free stretches first.
  const floor = onStage.filter((entry) => entry.placement === "ground" || entry.placement === "table");
  const gaps = freeGaps(standing).sort((a, b) => b.to - b.from - (a.to - a.from));
  // More props than gaps: split the widest.
  while (floor.length > gaps.length && gaps.length > 0) {
    const widest = gaps.shift()!;
    const middle = (widest.from + widest.to) / 2;
    gaps.push({ from: widest.from, to: middle }, { from: middle, to: widest.to });
    gaps.sort((a, b) => b.to - b.from - (a.to - a.from));
  }
  floor.forEach((item, index) => {
    const gap = gaps[index] ?? { from: 40, to: 60 };
    const full = PROP_HEIGHT[item.size];
    const room = gap.to - gap.from - 1;
    const scale = Math.min(1, room / widthOf(full, 1));
    const fits = scale >= MIN_SCALE;
    const onTable = item.placement === "table";
    slots.set(item.prop.id, {
      x: (gap.from + gap.to) / 2,
      bottom: (fits ? GROUND : GROUND - 4) + (onTable ? TABLE_HEIGHT : 0),
      height: full * Math.max(MIN_SCALE, Math.min(1, scale)),
      z: fits ? 2 : 3,
      onTable,
    });
  });

  return slots;
}

/* -------------------------------------------------------------------------- */
/* Which props are on stage, step by step                                      */
/* -------------------------------------------------------------------------- */

export interface StepProps {
  /** On stage at this step, in a stable order. */
  props: string[];
  /** Popping in at this step. */
  entering: string[];
  /** Named by this step's line: they bounce (or pop in). */
  pointed: string[];
}

const POINTING_STEPS: ReadonlySet<string> = new Set(["say", "narrate", "concept"]);

/** The props a step points at: a line's `props`, or a close-up's prop. */
export function pointedBy(step: Step, known: ReadonlyMap<string, Prop>): string[] {
  const ids: string[] = [];
  if (POINTING_STEPS.has(step.type) && Array.isArray(step.props)) {
    for (const id of step.props) if (typeof id === "string" && known.has(id)) ids.push(id);
  }
  const closeUp = closeUpProp(step);
  if (closeUp && known.has(closeUp)) ids.push(closeUp);
  return [...new Set(ids)].slice(0, 2);
}

/** The prop id of a close-up step (`show` with visual "prop"), if it is one. */
export function closeUpProp(step: Step): string | undefined {
  if (step.type !== "show" || step.visual !== "prop") return undefined;
  const id = step.params?.prop;
  return typeof id === "string" && id ? id : undefined;
}

/**
 * The props on stage at each step of one scene.
 *
 * Scenery, and any prop of the scene no line points at, is there from the
 * scene's first step. A prop a line points at pops in at its first mention
 * and bounces at the next ones. At most two props stand in front of the cast
 * and one piece of scenery: a third foreground prop sends off the one named
 * least recently. `carried` are the props already on stage from the scene
 * before at the same place: they stay without popping in again.
 */
export function planSceneProps(
  sceneProps: readonly string[] | undefined,
  steps: readonly Step[],
  known: ReadonlyMap<string, Prop>,
  carried: readonly string[] = [],
): StepProps[] {
  const declared = (sceneProps ?? []).filter((id) => known.has(id));
  const pointedAt = new Set(steps.flatMap((step) => pointedBy(step, known)));
  const scenery = (id: string) => isScenery(placementOf(known.get(id)!));

  // Order of last mention, for evicting the stalest foreground prop.
  const lastNamed = new Map<string, number>();
  let onStage: string[] = carried.filter((id) => known.has(id));
  const enteringFirst: string[] = [];
  for (const id of declared) {
    if (onStage.includes(id)) continue;
    if (scenery(id) || !pointedAt.has(id)) {
      onStage.push(id);
      enteringFirst.push(id);
    }
  }
  onStage = trim(onStage, scenery, lastNamed);
  const out: StepProps[] = [];
  steps.forEach((step, index) => {
    const pointed = pointedBy(step, known);
    const entering = index === 0 ? enteringFirst.filter((id) => onStage.includes(id)) : [];
    for (const id of pointed) {
      lastNamed.set(id, index);
      if (!onStage.includes(id)) {
        onStage.push(id);
        entering.push(id);
      }
    }
    onStage = trim(onStage, scenery, lastNamed, pointed);
    out.push({
      props: [...onStage],
      entering: entering.filter((id) => onStage.includes(id)),
      pointed: pointed.filter((id) => onStage.includes(id)),
    });
  });
  return out;
}

/** Keep at most MAX_FOREGROUND foreground and MAX_SCENERY scenery props. */
function trim(
  ids: string[],
  scenery: (id: string) => boolean,
  lastNamed: ReadonlyMap<string, number>,
  keep: readonly string[] = [],
): string[] {
  const back = ids.filter(scenery);
  const front = ids.filter((id) => !scenery(id));
  const pick = (list: string[], max: number) => {
    if (list.length <= max) return list;
    // The least recently named go first; the ones this line names never do.
    const ranked = [...list].sort((a, b) => {
      const keepA = keep.includes(a) ? 1 : 0;
      const keepB = keep.includes(b) ? 1 : 0;
      if (keepA !== keepB) return keepB - keepA;
      return (lastNamed.get(b) ?? -1) - (lastNamed.get(a) ?? -1);
    });
    const kept = new Set(ranked.slice(0, max));
    return list.filter((id) => kept.has(id));
  };
  const keptBack = pick(back, MAX_SCENERY);
  const keptFront = pick(front, MAX_FOREGROUND);
  return ids.filter((id) => keptBack.includes(id) || keptFront.includes(id));
}

/* -------------------------------------------------------------------------- */
/* Tokens and pictures                                                         */
/* -------------------------------------------------------------------------- */

const MEDIA_PATH = /^\/api\/v1\/(story-art|story-props|source-images)\/[0-9a-f][0-9a-f-]{7,63}\/data(\?[\w=&.-]*)?$/i;

/** Only the app's own story media is ever put in an `<img>`. */
export function sameOriginMedia(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const url = value.trim();
  return MEDIA_PATH.test(url) ? url : undefined;
}

export type PropToken =
  | { kind: "sticker"; src: string }
  | { kind: "polaroid"; src: string }
  | { kind: "emoji"; emoji: string }
  | { kind: "label" };

/** One pictographic grapheme, or nothing (a stray word is not an emoji). */
function cleanEmoji(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 16) return undefined;
  if (!/\p{Extended_Pictographic}/u.test(trimmed)) return undefined;
  if (/[\p{L}\p{N}]/u.test(trimmed.replace(/\p{Extended_Pictographic}|️|‍|\p{Emoji_Modifier}/gu, ""))) {
    return undefined;
  }
  return trimmed;
}

/** Colour emoji fonts first, so an emoji is drawn in colour where the device has one. */
export const EMOJI_FONTS = "'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif";

const drawnEmoji = new Map<string, boolean>();
let missingGlyph: Uint8ClampedArray | null | undefined;

function drawn(text: string): Uint8ClampedArray | null {
  const context = new OffscreenCanvas(24, 24).getContext("2d");
  if (!context) return null;
  context.font = `20px ${EMOJI_FONTS}`;
  context.textBaseline = "top";
  context.fillStyle = "#000000";
  context.fillText(text, 0, 2);
  return context.getImageData(0, 0, 24, 24).data;
}

/**
 * Whether this device really draws an emoji, rather than an empty box: an
 * older phone lacks the newer ones (🪨 is from 2020), and a box on the stage
 * says less than the thing's name. Drawn means in colour, or at least not
 * the box a missing character gets. Without a canvas to try it on, it is
 * taken as drawn.
 */
export function emojiDrawn(emoji: string): boolean {
  const known = drawnEmoji.get(emoji);
  if (known !== undefined) return known;
  let result = true;
  try {
    if (typeof OffscreenCanvas !== "undefined") {
      const pixels = drawn(emoji);
      if (missingGlyph === undefined) missingGlyph = drawn("\u{10FFFD}");
      if (pixels) {
        let coloured = false;
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 3] > 0 && (pixels[i] !== pixels[i + 1] || pixels[i + 1] !== pixels[i + 2])) {
            coloured = true;
            break;
          }
        }
        const blank = !pixels.some((value, i) => i % 4 === 3 && value > 0);
        const sameAsMissing = !!missingGlyph && pixels.every((value, i) => value === missingGlyph![i]);
        result = coloured || (!blank && !sameAsMissing);
      }
    }
  } catch {
    result = true;
  }
  drawnEmoji.set(emoji, result);
  return result;
}

/**
 * How a prop is drawn on stage: its cut-out sticker, else (in front of the
 * cast only) its photo in a polaroid frame, else its emoji, else a name tag.
 */
export function tokenFor(prop: Prop, media: PropMedia | undefined, placement: PropPlacement): PropToken {
  const sticker = sameOriginMedia(media?.sticker);
  if (sticker) return { kind: "sticker", src: sticker };
  const photo = sameOriginMedia(media?.picture?.src);
  if (photo && !isScenery(placement)) return { kind: "polaroid", src: photo };
  const emoji = cleanEmoji(prop.emoji);
  if (emoji) return { kind: "emoji", emoji };
  return { kind: "label" };
}

/** A course figure's credit line, in both languages. */
function courseCredit(prop: Prop): PropPicture["credit"] {
  const figure = prop.figure;
  const parts = (from: string) =>
    [from, figure?.figure_number, figure?.attribution].filter(Boolean).join(" · ");
  return {
    kind: "course",
    title: figure?.figure_number,
    text: { en: parts("From the course"), fr: parts("Tiré du cours") },
  };
}

/**
 * The picture a prop's close-up shows: its served picture, else the course
 * figure the builder resolved, else its sticker drawn large, else nothing.
 */
export function pictureFor(prop: Prop, media: PropMedia | undefined, lang: "fr" | "en"): PropPicture | undefined {
  const served = media?.picture;
  const servedSrc = sameOriginMedia(served?.src);
  if (served && servedSrc && served.credit?.text) {
    return {
      ...served,
      src: servedSrc,
      src_large: sameOriginMedia(served.src_large),
      width: Number(served.width) > 0 ? Number(served.width) : 4,
      height: Number(served.height) > 0 ? Number(served.height) : 3,
    };
  }
  const figure = prop.figure;
  if (figure?.source_image_id && /^[0-9a-f-]{8,64}$/i.test(figure.source_image_id)) {
    return {
      src: `/api/v1/source-images/${figure.source_image_id}/data?lang=${lang}`,
      width: 4,
      height: 3,
      alt: figure.alt ?? prop.label,
      caption: figure.caption,
      via: "lesson_figure",
      credit: courseCredit(prop),
    };
  }
  const sticker = sameOriginMedia(media?.sticker);
  if (sticker) {
    return {
      src: sticker,
      width: 1,
      height: 1,
      alt: prop.label,
      via: "ai_drawing",
      credit: { kind: "generated", text: { en: "Drawing made with AI", fr: "Dessin fait par une IA" } },
    };
  }
  return undefined;
}

/** "CC-BY-SA-4.0" → "CC BY-SA 4.0"; "CC0-1.0" → "CC0 1.0"; "PDM" → undefined (said in words). */
export function licenseLabel(code: string | undefined): string | undefined {
  if (!code) return undefined;
  if (/^pdm$/i.test(code)) return undefined;
  const cc0 = /^cc0-?([\d.]+)?$/i.exec(code);
  if (cc0) return `CC0${cc0[1] ? ` ${cc0[1]}` : ""}`;
  const by = /^cc-(by(?:-sa)?)-([\d.]+)$/i.exec(code);
  if (by) return `CC ${by[1].toUpperCase()} ${by[2]}`;
  return code;
}

/** The learner asked to save data, or the link is 2G: no large or eager photos. */
export function savesData(): boolean {
  if (typeof navigator === "undefined") return false;
  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;
  if (!connection) return false;
  return !!connection.saveData || connection.effectiveType === "slow-2g" || connection.effectiveType === "2g";
}

/** A prop's label in one language, for alt text and name tags. */
export function propLabel(prop: Prop, lang: string, fallback: string): string {
  return text(prop.label as TextObject, lang, fallback) || prop.id.replace(/_/g, " ");
}
