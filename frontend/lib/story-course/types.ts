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

/** A cast member's part in the story (contract #2672). */
export type CastRole = "hero" | "friend" | "mentor" | "family" | "tutor";

/** One way the hero can look; the learner picks one at the start (#2672). */
export interface CastVariant {
  /** `girl`/`boy` for kids courses, `woman`/`man` for adult ones. */
  id: string;
  /** One English sentence for the image model. */
  look?: string;
}

export interface CastMember {
  id: string;
  name: string;
  kind: "child" | "adult" | "animal" | "ai_tutor";
  art: string;
  voice?: Voice;
  /** Absent on stories written before the cartoon stage (#2672). */
  role?: CastRole;
  /** One English sentence for the image model: age, build, skin, hair, clothes. */
  look?: string;
  /** Hero only: the looks the learner chooses between. */
  variants?: CastVariant[];
  /** Friend only: the name used when the learner types none. */
  default_name?: string;
}

/** A place a scene is set in, one set per course (#2672). */
export interface Place {
  id: string;
  title?: TextObject;
  /** English backdrop description for the image model. */
  look?: string;
}

/**
 * Generated art, attached by the API when it serves a story and never written
 * by the model (#2672). Any key or pose may be missing: the player draws a
 * placeholder for it.
 */
export interface StoryArt {
  status?: "ready" | "pending" | "partial" | "none";
  /** Keyed by cast id, or `hero:<variant>` for the hero; then by pose. */
  characters?: Record<string, Partial<Record<string, string>>>;
  /** Backdrop URL per place id. */
  places?: Record<string, string>;
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
  /**
   * Set on a question copied verbatim from a quiz unit's MCQ (contract C-1):
   * the quiz unit's number and the quiz's own question id. Absent on the
   * extra questions the story writes itself.
   */
  derived_from?: DerivedFrom;
}

export interface DerivedFrom {
  quiz_unit: string;
  question_id: string;
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
  /**
   * The deterministic frame lines of a lesson chapter (contract C-1). The
   * module assembler rewrites steps by this marker, never by their text.
   */
  frame?: StepFrame;
}

export type StepFrame = "opener" | "objectives" | "finished" | "ask_tutor";

export interface Scene {
  id: string;
  /** A `places` id, or a key of the older built-in catalog. */
  place: string;
  objective?: string;
  /** Cast ids on stage, two or three (#2672). Absent on older stories. */
  cast?: string[];
  steps: Step[];
}

export interface Chapter {
  id: string;
  title: TextObject;
  scenes: Scene[];
  /** Which module unit this chapter tells; set on module stories only. */
  covers?: ChapterCovers;
}

/**
 * How a module story treats a unit (contract C-2): a lesson is retold as a
 * chapter; a quiz or a case study is a short checkpoint scene that sends the
 * learner to the unit's own page.
 */
export type ModuleUnitRole = "lesson" | "quiz_checkpoint" | "case_checkpoint";

/** The `covers` block of a module story chapter (contract C-2). */
export interface ChapterCovers {
  /** The unit's UUID: the key resume progress is stored under. */
  module_unit_id: string;
  /** "1.2": the id the completion API and the unit route take. */
  unit_number: string;
  unit_type: string | null;
  role: ModuleUnitRole;
  /**
   * ready: a lesson told as a chapter; unavailable: a lesson whose chapter
   * could not be written (a "read it on its page" placeholder); checkpoint: a
   * quiz or case-study unit.
   */
  status: "ready" | "unavailable" | "checkpoint";
  /** True only for a ready lesson chapter: finishing it completes the unit. */
  completes_unit: boolean;
  /** The chapter's own `checks.max_points` (0 for checkpoints). */
  max_points: number;
}

/** The top-level `module_story` block of a module story (contract C-2). */
export interface ModuleStoryMeta {
  module_id: string;
  module_number: number;
  assembler: number;
  /** Changes whenever any chapter changes. */
  revision: string;
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
  /** The course's places (#2672); older stories use catalog keys only. */
  places?: Place[];
  /** Generated art (#2672), attached by the API, never by the model. */
  art?: StoryArt;
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
  /** Set on a module story (one per module and language). */
  module_story?: ModuleStoryMeta;
  /** The chapter builder version a lesson chapter was written with. */
  sira_builder?: number;
}

/**
 * What the module page learns about a module story without downloading it
 * (`GET /api/v1/story-courses/module/{id}/status`, contract C-4).
 */
export interface ModuleStoryStatus {
  state: "ready" | "generating" | "not_ready" | "unavailable" | "disabled";
  task_id: string | null;
  chapters: number | null;
  revision: string | null;
  access: "ok" | "subscription_required";
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
