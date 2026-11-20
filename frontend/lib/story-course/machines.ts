/**
 * The idea machines of the story player (#2740: `place_value` and
 * `number_line`; #2756: `balance`, `cycle` and `cause_chain`).
 * Everything here is pure: the checks of their params (the same rules as
 * `story_course_validator.py`), the named parts a character can point at, the
 * picture as a function of a step index, and the words of the alt text. The
 * lazy chunks only draw what these functions say.
 */

import { pick } from "@/components/story/demos/shared";

export const PLACE_VALUE_GROUPS = ["ones", "thousands", "millions", "billions"] as const;
export const PLACE_VALUE_MAX_DIGITS = 12;
export const NUMBER_LINE_MAX_TICKS = 20;
/** The ball rolls from `from` to `mark` in this many stills. */
export const LINE_STEPS = 4;

/** A label is {en, fr}, each language 1 to this many characters once spaces are collapsed. */
export const LABEL_LIMIT = 40;
export const BALANCE_MAX = 100000;
export const CYCLE_STAGES = [3, 6] as const;
export const CHAIN_LINKS = [2, 5] as const;

export type MachineVisual = "place_value" | "number_line" | "balance" | "cycle" | "cause_chain";
type Params = Record<string, unknown>;

/**
 * When the machine of the current step should start, in ms from now, or null
 * when it must wait (no machine, intro or beat still open, step seen again).
 * A tap that cut the beat short starts it at once.
 */
export function machineStartDelay(s: {
  hasMachine: boolean;
  introOpen: boolean;
  beatOn: boolean;
  revisit: boolean;
  cut: boolean;
  machineAt?: number;
}): number | null {
  if (!s.hasMachine || s.introOpen || s.beatOn || s.revisit) return null;
  return s.cut ? 0 : (s.machineAt ?? 0);
}

const MACHINES = ["place_value", "number_line", "balance", "cycle", "cause_chain"];
export const isMachineVisual = (visual: unknown): visual is MachineVisual => MACHINES.includes(visual as string);

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

type Label = { en: string; fr: string };

/** A label with both languages, 1 to LABEL_LIMIT characters after collapsing spaces (as the validator does). */
function isLabel(value: unknown): value is Label {
  if (!value || typeof value !== "object") return false;
  return (["en", "fr"] as const).every((lang) => {
    const text = (value as Params)[lang];
    const length = typeof text === "string" ? [...text.replace(/\s+/g, " ").trim()].length : 0;
    return length > 0 && length <= LABEL_LIMIT;
  });
}

/** `value` as a list of labels when it holds `range[0]` to `range[1]` of them. */
function labelsOf(value: unknown, range: readonly [number, number]): Label[] | null {
  const ok = Array.isArray(value) && value.length >= range[0] && value.length <= range[1] && value.every(isLabel);
  return ok ? (value as Label[]) : null;
}

interface Side {
  label: Label;
  value: number;
}

/** One pan of the balance: a label and a value from 0 to BALANCE_MAX. */
function sideOf(value: unknown): Side | null {
  const side = (value && typeof value === "object" ? value : {}) as Params;
  const { label, value: weight } = side;
  return isLabel(label) && isNumber(weight) && weight >= 0 && weight <= BALANCE_MAX ? { label, value: weight } : null;
}

const named = (prefix: string, count: number) => Array.from({ length: count }, (_, i) => prefix + (i + 1));

/** The digits of `n` when it is a whole number of 0 to 12 digits, else null. */
function digitsOf(n: unknown): string | null {
  if (!isNumber(n) || !Number.isInteger(n) || n < 0 || n >= 10 ** PLACE_VALUE_MAX_DIGITS) return null;
  return String(n);
}

/** The parts a machine can name, smallest first. Same lists and order as `machine_parts` in the validator. */
export function partsOf(visual: string, params: unknown): string[] {
  if (!params || typeof params !== "object" || Array.isArray(params)) return [];
  const p = params as Params;
  if (visual === "place_value") {
    const digits = digitsOf(p.n);
    return digits === null ? [] : PLACE_VALUE_GROUPS.slice(0, Math.ceil(digits.length / 3));
  }
  if (visual === "number_line") {
    if (!isNumber(p.from) || !isNumber(p.to)) return [];
    return p.mark == null ? ["from", "to"] : ["from", "to", "mark"];
  }
  // Parts depend on the structure only, never on `start` or `highlight`.
  if (visual === "balance") return sideOf(p.left) && sideOf(p.right) ? ["left", "right", "beam"] : [];
  if (visual === "cycle") return named("stage", labelsOf(p.stages, CYCLE_STAGES)?.length ?? 0);
  if (visual === "cause_chain") return named("link", labelsOf(p.links, CHAIN_LINKS)?.length ?? 0);
  return [];
}

export interface PlaceValueModel {
  /** The digits of n, most significant first. */
  digits: string;
  /** Groups present, smallest first: a part id each. */
  groups: (typeof PLACE_VALUE_GROUPS)[number][];
  reveal: "groups" | "all";
  highlight?: string;
}

export interface NumberLineModel {
  from: number;
  to: number;
  mark: number | null;
  /** Tick values, ends included. */
  ticks: number[];
  highlight?: string;
}

/** The place-value machine for `params`, or null when they cannot be drawn. */
export function placeValueModel(params: unknown): PlaceValueModel | null {
  const p = (params && typeof params === "object" ? params : {}) as Params;
  const digits = digitsOf(p.n);
  if (digits === null) return null;
  if (p.reveal != null && p.reveal !== "groups" && p.reveal !== "all") return null;
  const groups = partsOf("place_value", p) as PlaceValueModel["groups"];
  if (p.highlight != null && !groups.includes(p.highlight as never)) return null;
  return {
    digits,
    groups,
    reveal: p.reveal === "all" ? "all" : "groups",
    highlight: p.highlight == null ? undefined : String(p.highlight),
  };
}

const round = (value: number) => Number(value.toPrecision(12));

/** Ticks for a line without a `step`: about five intervals on a round value. */
function niceStep(span: number): number {
  const raw = span / 5;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const unit = [1, 2, 5, 10].find((m) => m * mag >= raw) ?? 10;
  return unit * mag;
}

/** The number-line machine for `params`, or null when they cannot be drawn. */
export function numberLineModel(params: unknown): NumberLineModel | null {
  const p = (params && typeof params === "object" ? params : {}) as Params;
  const { from, to, mark, step } = p;
  if (!isNumber(from) || !isNumber(to) || !(from < to)) return null;
  if (mark != null && !(isNumber(mark) && from <= mark && mark <= to)) return null;
  if (step != null && !(isNumber(step) && step > 0 && (to - from) / step <= NUMBER_LINE_MAX_TICKS + 1e-9)) {
    return null;
  }
  if (p.highlight != null && !(typeof p.highlight === "string" && partsOf("number_line", p).includes(p.highlight))) return null;
  const gap = isNumber(step) ? step : niceStep(to - from);
  const ticks = [from];
  // Bounded by a count, so a huge `from` (where k++ stops changing k) cannot hang the player.
  // With a `step` the ticks sit at from + k * step; the automatic step uses round multiples.
  const last = NUMBER_LINE_MAX_TICKS + 2;
  const start = isNumber(step) ? 1 : Math.ceil(from / gap + 1e-9);
  for (let i = 0; i <= last; i++) {
    const value = isNumber(step) ? round(from + (start + i) * gap) : round((start + i) * gap);
    if (value >= to) break;
    if (value > ticks[ticks.length - 1]) ticks.push(value);
  }
  if (to > ticks[ticks.length - 1]) ticks.push(to);
  return {
    from,
    to,
    mark: mark == null ? null : (mark as number),
    ticks,
    highlight: p.highlight == null ? undefined : String(p.highlight),
  };
}

/** The highlight of `params` when it names a part, "" when absent, null when it is not a part. */
function highlightOf(visual: string, params: Params): string | null {
  if (params.highlight == null) return "";
  return typeof params.highlight === "string" && partsOf(visual, params).includes(params.highlight) ? params.highlight : null;
}

export interface BalanceModel {
  left: Side;
  right: Side;
  /** The larger side; null when the values are equal (the beam stays level). */
  heavier: "left" | "right" | null;
  highlight?: string;
}

/** The balance for `params`, or null when they cannot be drawn. */
export function balanceModel(params: unknown): BalanceModel | null {
  const p = (params && typeof params === "object" ? params : {}) as Params;
  const [left, right, highlight] = [sideOf(p.left), sideOf(p.right), highlightOf("balance", p)];
  if (!left || !right || highlight === null) return null;
  const heavier = left.value === right.value ? null : left.value > right.value ? "left" : "right";
  return { left, right, heavier, highlight: highlight || undefined };
}

export interface CycleModel {
  stages: Label[];
  /** The stage the marker starts at, 0-based. */
  start: number;
  highlight?: string;
}

/** The cycle for `params`, or null when they cannot be drawn. `start` is 1-based, 1 to the number of stages. */
export function cycleModel(params: unknown): CycleModel | null {
  const p = (params && typeof params === "object" ? params : {}) as Params;
  const stages = labelsOf(p.stages, CYCLE_STAGES);
  const start = p.start == null ? 1 : p.start;
  const highlight = highlightOf("cycle", p);
  if (!stages || highlight === null) return null;
  if (!(isNumber(start) && Number.isInteger(start) && start >= 1 && start <= stages.length)) return null;
  return { stages, start: start - 1, highlight: highlight || undefined };
}

export interface ChainModel {
  links: Label[];
  highlight?: string;
}

/** The cause chain for `params`, or null when they cannot be drawn. */
export function chainModel(params: unknown): ChainModel | null {
  const p = (params && typeof params === "object" ? params : {}) as Params;
  const links = labelsOf(p.links, CHAIN_LINKS);
  const highlight = highlightOf("cause_chain", p);
  return links && highlight !== null ? { links, highlight: highlight || undefined } : null;
}

/** The model of any idea machine, or null when its params cannot be drawn. */
export function machineModel(visual: string, params: unknown): object | null {
  const models: Record<string, (params: unknown) => object | null> = {
    place_value: placeValueModel,
    number_line: numberLineModel,
    balance: balanceModel,
    cycle: cycleModel,
    cause_chain: chainModel,
  };
  return models[visual]?.(params) ?? null;
}

/** The last step of a machine: step 0 is the empty picture. */
export function placeValueLast(model: PlaceValueModel): number {
  return model.reveal === "all" ? 1 : model.groups.length;
}
export const numberLineLast = (model: NumberLineModel): number => (model.mark === null ? 0 : LINE_STEPS);

/** The balance tilts in one step, or never when level. */
export const balanceLast = (model: BalanceModel): number => (model.heavier ? 1 : 0);
/** The marker goes once round the ring and back to its start. */
export const cycleLast = (model: CycleModel): number => model.stages.length;
export const chainLast = (model: ChainModel): number => model.links.length;

const clampStep = (step: number, last: number) => Math.max(0, Math.min(Math.floor(step), last));

/** The beam as an SVG rotation in degrees: negative when the left side is down, 0 when level or not yet tilted. */
export function beamAngle(model: BalanceModel, step: number): number {
  if (!model.heavier || clampStep(step, 1) < 1) return 0;
  const { left, right } = model;
  const tilt = Math.max(6, (16 * Math.abs(left.value - right.value)) / Math.max(left.value, right.value));
  return model.heavier === "left" ? -tilt : tilt;
}

/** The stage (0-based) the marker is on at `step`: it visits each stage once, then returns to the start. */
export const markerAt = (model: CycleModel, step: number): number =>
  (model.start + clampStep(step, model.stages.length)) % model.stages.length;

/** How many links are lit at `step`, in order. */
export const linksLit = (model: ChainModel, step: number): number => clampStep(step, model.links.length);

/** `text` cut into lines of at most `width` characters, at spaces; a longer word is cut. */
export function wrapLabel(text: string, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (let word of text.replace(/\s+/g, " ").trim().split(" ")) {
    for (; word.length > width; word = word.slice(width)) {
      if (line) lines.push(line);
      line = "";
      lines.push(word.slice(0, width));
    }
    if (line && line.length + 1 + word.length > width) {
      lines.push(line);
      line = word;
    } else line = line ? `${line} ${word}` : word;
  }
  return line ? [...lines, line] : lines;
}

/** How many groups (from the right) have dropped into their columns at `step`. */
export function groupsPlaced(model: PlaceValueModel, step: number): number {
  const at = Math.max(0, Math.min(Math.floor(step), placeValueLast(model)));
  return model.reveal === "all" ? (at >= 1 ? model.groups.length : 0) : at;
}

/** Where the ball is at `step`, as a value on the line. */
export function ballAt(model: NumberLineModel, step: number): number {
  if (model.mark === null) return model.from;
  const at = Math.max(0, Math.min(Math.floor(step), LINE_STEPS));
  return model.from + ((model.mark - model.from) * at) / LINE_STEPS;
}

/* ------------------------------ alt text ------------------------------ */

/** A number written for `lang`: groups of three (thin space in French, comma in English). */
export function formatNumber(value: number, lang: "fr" | "en"): string {
  const [whole, fraction] = String(round(value)).split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const grouped = whole.replace("-", "").replace(/\B(?=(\d{3})+$)/g, lang === "fr" ? " " : ",");
  return sign + grouped + (fraction ? (lang === "fr" ? "," : ".") + fraction : "");
}

type Say = (key: string, values?: Record<string, string | number>) => string;

/** The alt text of a machine in the learner's language, or null when its params cannot be drawn. */
export function machineAlt(visual: string, params: unknown, lang: "fr" | "en", say: Say): string | null {
  if (visual === "place_value") {
    const model = placeValueModel(params);
    if (!model) return null;
    const number = formatNumber(Number(model.digits), lang);
    const spoken: string[] = [];
    model.groups.forEach((group, at) => {
      const part = Number(model.digits.slice(Math.max(0, model.digits.length - 3 * (at + 1)), model.digits.length - 3 * at));
      if (part === 0) return;
      spoken.unshift(group === "ones" ? String(part) : say(`machineGroup_${group}`, { count: part }));
    });
    return model.groups.length === 1 || spoken.length === 0
      ? number
      : say("machinePlaceValueAlt", { number, groups: spoken.join(", ") });
  }
  if (visual === "number_line") {
    const model = numberLineModel(params);
    if (!model) return null;
    const values = { from: formatNumber(model.from, lang), to: formatNumber(model.to, lang) };
    return model.mark === null
      ? say("machineLineAlt", values)
      : say("machineLineAltMark", { ...values, mark: formatNumber(model.mark, lang) });
  }
  if (visual === "balance") {
    const model = balanceModel(params);
    if (!model) return null;
    const { left, right, heavier } = model;
    return say(heavier ? (heavier === "left" ? "machineBalanceAltLeft" : "machineBalanceAltRight") : "machineBalanceAltEqual", {
      left: pick(left.label, lang),
      leftValue: formatNumber(left.value, lang),
      right: pick(right.label, lang),
      rightValue: formatNumber(right.value, lang),
    });
  }
  if (visual === "cycle" || visual === "cause_chain") {
    const model = visual === "cycle" ? cycleModel(params) : chainModel(params);
    if (!model) return null;
    const items = ("stages" in model ? model.stages : model.links).map((label) => pick(label, lang));
    return visual === "cycle"
      ? say("machineCycleAlt", { count: items.length, stages: items.join(", "), first: items[(model as CycleModel).start] })
      : say("machineChainAlt", { count: items.length, links: items.join(", ") });
  }
  return null;
}
