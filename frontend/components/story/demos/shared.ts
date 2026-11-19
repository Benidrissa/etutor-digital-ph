/**
 * What the four demo primitives (#2711: compare, annotate, sort, timeline)
 * share: their props and the readers of their data. Each demo is a lazy chunk
 * of its own; this file is a few lines so it can sit in each of them.
 *
 * The verdict of a demo is read from its data (`values`, `expected`, `bin`,
 * `at`), never from pixels.
 */

export interface DemoProps {
  params: Record<string, unknown>;
  lang: "fr" | "en";
  /** The learner acted and saw the verdict: the bet may be revealed. */
  onDone?: (outcome: { correct: boolean }) => void;
}

export type Pair = { en?: string; fr?: string };

/** A `{en, fr}` label in `lang`, else the other language, else "". */
export function pick(value: unknown, lang: "fr" | "en"): string {
  const pair = (value && typeof value === "object" ? value : {}) as Pair;
  return pair[lang] ?? pair[lang === "fr" ? "en" : "fr"] ?? "";
}

export const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
