/**
 * The idea machines of the story player (#2740): `place_value` and
 * `number_line`. Everything here is pure: the checks of their params (the
 * same rules as `story_course_validator.py`), the named parts a character can
 * point at, the picture as a function of a step index, and the words of the
 * alt text. The two lazy chunks only draw what these functions say.
 */

export const PLACE_VALUE_GROUPS = ["ones", "thousands", "millions", "billions"] as const;
export const PLACE_VALUE_MAX_DIGITS = 12;
export const NUMBER_LINE_MAX_TICKS = 20;
/** The ball rolls from `from` to `mark` in this many stills. */
export const LINE_STEPS = 4;

export type MachineVisual = "place_value" | "number_line";
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

export const isMachineVisual = (visual: unknown): visual is MachineVisual =>
  visual === "place_value" || visual === "number_line";

const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);

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

/** The last step of a machine: step 0 is the empty picture. */
export function placeValueLast(model: PlaceValueModel): number {
  return model.reveal === "all" ? 1 : model.groups.length;
}
export const numberLineLast = (model: NumberLineModel): number => (model.mark === null ? 0 : LINE_STEPS);

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
  return null;
}
