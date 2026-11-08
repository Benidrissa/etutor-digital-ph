/**
 * Answer acceptance for the story player (format Appendix A.5).
 *
 * Scope: this module decides whether what the child typed matches the answer
 * the course file already carries. It deliberately does NOT recompute the
 * maths — the backend validator does that with the Python engine before a week
 * can be published, so by the time the player sees an answer it has been
 * verified. Duplicating the engine in TypeScript would mean two
 * implementations that could disagree, and a disagreement here would mark a
 * correct answer wrong in front of a learner.
 *
 * What it does handle is the generosity A.5 requires: a child on a phone types
 * `2^3` for `2³`, `08h36` for `08:36`, `4 284` or `4,284` for 4284, and a
 * French keyboard produces `3,25`. None of those should cost her a mark.
 */

import type { Question, QuestionType, TextObject, Trap } from "./types";

export interface MatchResult {
  correct: boolean;
  /** She used a decimal comma: accept, but show the decimal-point reminder. */
  decimalCommaUsed?: boolean;
  /** Right primes, but not written with powers, and `require_index` is set. */
  needsIndexForm?: boolean;
}

const SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹";
/** U+2212 MINUS SIGN, the sign A.2 mandates in authored text. */
const MINUS = "−";
const SPACES = /[\s   ]/g;

function stripSpaces(text: string): string {
  return text.replace(SPACES, "");
}

/** Fold authored Unicode onto ASCII: minus sign, times, divide. */
function foldSigns(text: string): string {
  return text
    .replace(new RegExp(MINUS, "g"), "-")
    .replace(/–|—/g, "-");
}

/**
 * Read a number the way A.5 says the app should: thousands spaces or commas,
 * the U+2212 minus, a trailing unit, and a decimal comma.
 */
export function parseLooseNumber(
  input: string,
): { value: number; decimalCommaUsed: boolean } | null {
  let text = foldSigns(stripSpaces(String(input)));
  if (!text) return null;

  let decimalCommaUsed = false;
  const commas = (text.match(/,/g) ?? []).length;
  if (commas === 1 && !/,\d{3}(?!\d)/.test(text)) {
    // A lone comma not in thousands position is a decimal separator.
    text = text.replace(",", ".");
    decimalCommaUsed = true;
  } else {
    text = text.replace(/,/g, "");
  }

  // Drop a trailing unit ("12cm" -> "12") but refuse leading junk.
  const match = /^[-+]?(?:\d+\.?\d*|\.\d+)/.exec(text);
  if (!match) return null;
  const value = Number(match[0]);
  if (!Number.isFinite(value)) return null;
  return { value, decimalCommaUsed };
}

/**
 * Canonicalise index form so `2^3`, `2³` and a reordered `3² × 2³ × 5` agree.
 *
 * The power structure is preserved on purpose: `2³ × 3² × 5` must NOT equal
 * `2 × 2 × 2 × 3 × 3 × 5`, because that expanded form is the documented
 * `m_not_index_form` trap and has its own hint.
 */
export function normalizeIndexForm(input: string): string {
  let text = stripSpaces(String(input)).toLowerCase();
  for (let i = 0; i < SUPERSCRIPTS.length; i += 1) {
    text = text.split(SUPERSCRIPTS[i]).join(`^${i}`);
  }
  text = text.replace(/×|x|\*|·/g, "*");
  const parts = text
    .split("*")
    .filter(Boolean)
    .map((part) => {
      const [base, power] = part.split("^");
      const baseNum = Number(base);
      const powerNum = power === undefined || power === "" ? 1 : Number(power);
      if (!Number.isFinite(baseNum) || !Number.isFinite(powerNum)) {
        return { base: Number.NaN, power: 0, raw: part };
      }
      return { base: baseNum, power: powerNum, raw: "" };
    });
  parts.sort((a, b) => a.base - b.base || a.power - b.power);
  return parts
    .map((p) => (p.raw ? p.raw : `${p.base}^${p.power}`))
    .join("*");
}

/** True when no base appears twice as a separate factor. */
export function isIndexForm(input: string): boolean {
  const bases = normalizeIndexForm(input)
    .split("*")
    .filter(Boolean)
    .map((part) => part.split("^")[0]);
  return new Set(bases).size === bases.length;
}

/**
 * Canonicalise a clock time to `HH:MM`.
 *
 * Accepts `8:36`, `08h36`, `8.36`, and a 12-hour `8.36 pm`.
 */
export function normalizeTime(input: string): string | null {
  const text = stripSpaces(String(input)).toLowerCase();
  const match = /^(\d{1,2})[:h.](\d{2})(am|pm)?$/.exec(text);
  if (!match) return null;
  let hours = Number(match[1]);
  const minutes = Number(match[2]);
  const suffix = match[3];
  if (minutes > 59) return null;
  if (suffix === "pm" && hours < 12) hours += 12;
  if (suffix === "am" && hours === 12) hours = 0;
  if (hours > 23) return null;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function splitList(input: string): string[] {
  return String(input)
    .split(/[,;]/)
    .map((piece) => piece.trim())
    .filter(Boolean);
}

function expectedAsList(expected: unknown): string[] {
  if (Array.isArray(expected)) return expected.map((item) => String(item));
  return splitList(String(expected ?? ""));
}

/**
 * Compare a typed answer against the authored one, by question type.
 *
 * `expected` is whatever the course file carries, so it may be a number, a
 * string or an array.
 */
export function matchAnswer(
  typed: string,
  expected: unknown,
  type: QuestionType,
  options: { order?: "ascending" | "any"; requireIndex?: boolean } = {},
): MatchResult {
  const trimmed = String(typed ?? "").trim();
  if (!trimmed) return { correct: false };

  switch (type) {
    case "choice":
      return {
        correct:
          stripSpaces(trimmed).toLowerCase() ===
          stripSpaces(String(expected ?? "")).toLowerCase(),
      };

    case "exact_text": {
      // "the same characters once spaces are removed (2.1 is not 2.10)"
      const got = foldSigns(stripSpaces(trimmed));
      const want = foldSigns(stripSpaces(String(expected ?? "")));
      return { correct: got === want };
    }

    case "index_form": {
      const correct =
        normalizeIndexForm(trimmed) === normalizeIndexForm(String(expected ?? ""));
      if (correct) return { correct: true };
      // Right primes but expanded: tell the caller so it can show the
      // index-form hint rather than a flat "wrong".
      const expandedMatchesValue =
        expandPowers(trimmed) === expandPowers(String(expected ?? ""));
      if (expandedMatchesValue && options.requireIndex && !isIndexForm(trimmed)) {
        return { correct: false, needsIndexForm: true };
      }
      return { correct: false };
    }

    case "time": {
      const got = normalizeTime(trimmed);
      const want = normalizeTime(String(expected ?? ""));
      return { correct: got !== null && got === want };
    }

    case "list": {
      const gotPieces = splitList(trimmed);
      const wantPieces = expectedAsList(expected);
      if (gotPieces.length !== wantPieces.length) return { correct: false };
      const gotNumbers = gotPieces.map(parseLooseNumber);
      const wantNumbers = wantPieces.map(parseLooseNumber);
      if (gotNumbers.some((n) => n === null) || wantNumbers.some((n) => n === null)) {
        // Fall back to text comparison for non-numeric lists.
        const normalize = (items: string[]) =>
          items.map((i) => stripSpaces(i).toLowerCase());
        const got = normalize(gotPieces);
        const want = normalize(wantPieces);
        return {
          correct:
            options.order === "any"
              ? [...got].sort().join("|") === [...want].sort().join("|")
              : got.join("|") === want.join("|"),
        };
      }
      const got = gotNumbers.map((n) => n!.value);
      const want = wantNumbers.map((n) => n!.value);
      const decimalCommaUsed = gotNumbers.some((n) => n!.decimalCommaUsed);
      const same =
        options.order === "any"
          ? [...got].sort((a, b) => a - b).join("|") ===
            [...want].sort((a, b) => a - b).join("|")
          : got.join("|") === want.join("|");
      return { correct: same, decimalCommaUsed };
    }

    case "number":
    default: {
      const got = parseLooseNumber(trimmed);
      const want = parseLooseNumber(String(expected ?? ""));
      if (got === null || want === null) return { correct: false };
      return {
        correct: got.value === want.value,
        decimalCommaUsed: got.decimalCommaUsed,
      };
    }
  }
}

/** Expand `2^3` to `2*2*2` so a value comparison ignores notation. */
function expandPowers(input: string): string {
  const normalized = normalizeIndexForm(input);
  const factors: number[] = [];
  for (const part of normalized.split("*").filter(Boolean)) {
    const [base, power] = part.split("^");
    const baseNum = Number(base);
    const powerNum = Number(power ?? 1);
    if (!Number.isFinite(baseNum) || !Number.isFinite(powerNum)) return normalized;
    for (let i = 0; i < powerNum; i += 1) factors.push(baseNum);
  }
  factors.sort((a, b) => a - b);
  return factors.join("*");
}

/**
 * Find the trap a wrong answer fell into, so its targeted hint can be shown.
 *
 * Traps are matched with the same generosity as the answer: a child who types
 * `2^3 x 3 x 5` has still fallen into the `2³ × 3 × 5` trap.
 */
export function findTrap(
  typed: string,
  question: Pick<Question, "type" | "traps" | "order" | "require_index">,
): Trap | null {
  for (const trap of question.traps ?? []) {
    if (trap.answer === undefined || trap.answer === null) continue;
    const { correct } = matchAnswer(typed, trap.answer, question.type, {
      order: question.order,
      requireIndex: false,
    });
    if (correct) return trap;
  }
  return null;
}

export interface Attempt {
  /** 1 for the first try, 2 for the second. */
  attempt: number;
  result: MatchResult;
  /** The trap she fell into, when there is one. */
  trap: Trap | null;
  /** Points earned: 2 on the first try, 1 on the second, 0 after that. */
  points: number;
  /** True once the app should reveal the explanation. */
  revealExplanation: boolean;
  /** The hint to show now, if any. */
  hint: TextObject | null;
}

/**
 * Score one submission and decide what the player shows next (A.5 flow):
 * a wrong answer gets the matching trap's hint, then a second try, then the
 * explanation.
 */
export function scoreAttempt(
  typed: string,
  question: Question,
  previousAttempts: number,
  rewards: { first_try?: number; second_try?: number } = {},
): Attempt {
  const attempt = previousAttempts + 1;
  const result = matchAnswer(typed, question.answer, question.type, {
    order: question.order,
    requireIndex: question.require_index,
  });

  if (result.correct) {
    const firstTry = rewards.first_try ?? 2;
    const secondTry = rewards.second_try ?? 1;
    return {
      attempt,
      result,
      trap: null,
      points: question.points ?? (attempt === 1 ? firstTry : attempt === 2 ? secondTry : 0),
      revealExplanation: true,
      hint: null,
    };
  }

  const trap = findTrap(typed, question);
  const revealExplanation = attempt >= 2;
  return {
    attempt,
    result,
    trap,
    points: 0,
    revealExplanation,
    // On the last try the explanation replaces the hint.
    hint: revealExplanation ? null : (trap?.hint ?? question.hints?.[0] ?? null),
  };
}

/** Pick the right language out of a text object, falling back to the other. */
export function text(
  obj: TextObject | undefined | null,
  lang: string,
  fallbackLang?: string,
): string {
  if (!obj) return "";
  return obj[lang] ?? (fallbackLang ? obj[fallbackLang] : undefined) ?? Object.values(obj)[0] ?? "";
}

/** Stars for a chapter, from the share of points won (A.11). */
export function starsFor(
  share: number,
  thresholds: Record<string, number> = { "3": 0.85, "2": 0.6 },
): number {
  const levels = Object.entries(thresholds)
    .map(([stars, min]) => ({ stars: Number(stars), min }))
    .sort((a, b) => b.stars - a.stars);
  for (const level of levels) {
    if (share >= level.min) return level.stars;
  }
  return share > 0 ? 1 : 0;
}
