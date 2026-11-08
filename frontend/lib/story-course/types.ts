/**
 * Types for the `story-course/1` course file format.
 *
 * These mirror `backend/app/api/v1/schemas/story_course.py`. The backend
 * validator is the authority on whether a file is well-formed, so the player
 * trusts the shape of a published week and only guards the places where a
 * learner's input meets it.
 */

/** A text object: one string per declared language code (A.2). */
export type TextObject = Record<string, string>;

export type StepType =
  | "narrate"
  | "say"
  | "show"
  | "concept"
  | "ask"
  | "game"
  | "photo"
  | "video";

export type QuestionType =
  | "number"
  | "exact_text"
  | "list"
  | "choice"
  | "index_form"
  | "time"
  | "multi";

export type Mood =
  | "idle"
  | "talk"
  | "happy"
  | "think"
  | "sad"
  | "surprised"
  | "walk";

export interface Languages {
  target: string;
  home: string;
}

export interface Objective {
  id: string;
  en: string;
  fr: string;
  syllabus?: string;
}

export interface Misconception {
  id: string;
  en: string;
  fr: string;
  from_test?: boolean;
}

export interface Voice {
  pitch?: number;
  rate?: number;
}

export interface CastMember {
  id: string;
  name: string;
  kind: "child" | "adult" | "animal" | "ai_tutor";
  art: string;
  voice?: Voice;
}

export interface GlossaryEntry {
  en: string;
  fr: string;
  note?: TextObject;
}

/** An engine call that recomputes an answer (A.7). Verified server-side. */
export interface Verify {
  fn: string;
  args?: unknown[];
  kwargs?: Record<string, unknown>;
}

export interface Trap {
  answer: unknown;
  misconception?: string;
  hint?: TextObject;
}

export interface Choice {
  id: string;
  en: string;
  fr: string;
  /** Absent on the correct option; present on every wrong one. */
  misconception?: string;
}

export interface QuestionPart {
  label?: string;
  type?: QuestionType;
  answer?: unknown;
  verify?: Verify;
  marks?: number;
}

export interface Question {
  id: string;
  type: QuestionType;
  objective?: string;
  calculator?: boolean;
  prompt: TextObject;
  answer?: unknown;
  verify?: Verify;
  traps?: Trap[];
  hints?: TextObject[];
  explanation?: TextObject;
  tutor_notes?: string;
  units?: string;
  order?: "ascending" | "any";
  choices?: Choice[];
  require_index?: boolean;
  parts?: QuestionPart[];
  review_of?: string | number;
  points?: number;
}

export interface MarkSchemeRow {
  code: "M1" | "A1" | "B1" | "SC1";
  en: string;
  fr: string;
}

export interface PhotoCheck {
  copy: string;
  check?: Record<string, unknown>;
}

export interface Exercise {
  id: string;
  part: "A" | "B" | "C" | "D";
  objective?: string;
  marks?: number;
  calculator?: boolean;
  prompt: TextObject;
  answer?: unknown;
  verify?: Verify;
  parts?: QuestionPart[];
  working?: Record<string, string[]>;
  mark_scheme?: MarkSchemeRow[];
  traps?: Trap[];
  explanation?: TextObject;
  photo_check?: PhotoCheck;
}

export interface Step {
  type: StepType;
  /** narrate/say carry flat strings; concept carries a row array. */
  en?: string | string[];
  fr?: string | string[];
  who?: string;
  mood?: Mood;
  visual?: string;
  params?: Record<string, unknown>;
  caption?: TextObject;
  id?: string;
  title?: TextObject;
  ref?: string;
}

export interface Scene {
  id: string;
  place: string;
  objective?: string;
  steps: Step[];
}

export interface Chapter {
  id: string;
  title: TextObject;
  scenes: Scene[];
}

/** One tappable thing in an items-shaped round (contract C5). */
export interface MinigameItem {
  label: TextObject | string;
  correct?: boolean;
  /** The misconception id a wrong item represents. Only on wrong items. */
  trap?: string;
}

/**
 * A round that lists its items explicitly, each flagged right or wrong — the
 * shape lesson stories use (engine `catch`), since a lesson's facts have no
 * rule a client could evaluate the way `is_prime` can.
 */
export interface MinigameItemsRound {
  prompt?: TextObject;
  items: MinigameItem[];
}

export interface Minigame {
  id: string;
  engine: string;
  objective?: string;
  title: TextObject;
  instruction: TextObject;
  rule?: { fn?: string };
  /**
   * Either a list of values the `rule` sorts into targets and traps (`pop`),
   * or {@link MinigameItemsRound} objects. Other shapes are not rendered.
   */
  rounds?: unknown[];
  traps?: Record<string, string>;
  hint_after_wrong?: TextObject;
  points?: { per_correct?: number };
  timer_s?: number;
  speed?: number;
  min?: number;
  max?: number;
}

export interface Video {
  id: string;
  provider: string;
  lang: string;
  title: string;
  url: string;
}

export interface Tutor {
  persona: string;
  intro: TextObject;
  scope?: { this_week?: string[]; earlier_weeks?: string };
  style?: string[];
  never?: string[];
  off_topic?: TextObject;
  worry?: TextObject;
  max_turns_per_item?: number;
}

export interface Rewards {
  unit?: TextObject;
  first_try?: number;
  second_try?: number;
  streak?: { every?: number; bonus?: number };
  stars?: Record<string, number>;
}

export interface StoryCourse {
  format: string;
  id: string;
  course: string;
  unit?: string;
  week: number;
  title: TextObject;
  languages: Languages;
  learner: { first_name: string; age?: number; gender?: string };
  objectives: Objective[];
  glossary?: GlossaryEntry[];
  misconceptions?: Misconception[];
  cast: CastMember[];
  facts?: { en: string; fr: string; source?: string; invented?: boolean }[];
  chapters: Chapter[];
  questions: Question[];
  exercises?: Exercise[];
  minigames?: Minigame[];
  videos?: Video[];
  tutor?: Tutor;
  rewards?: Rewards;
  art_requests?: { name: string; kind: string; description: string }[];
  engine_requests?: Record<string, unknown>[];
  checks?: Record<string, unknown>;
}

/** A catalog row (the app's `catalog.json`). */
export interface StoryCourseListItem {
  id: string;
  course: string;
  unit?: string | null;
  week: number;
  title: TextObject;
  languages: Languages;
  objective_count: number;
  question_count: number;
  exercise_count: number;
  max_points: number;
  is_valid: boolean;
}

export interface StoryCourseListResponse {
  items: StoryCourseListItem[];
  total: number;
}

export const REWARD_DEFAULTS: Required<
  Pick<Rewards, "first_try" | "second_try">
> = {
  first_try: 2,
  second_try: 1,
};
