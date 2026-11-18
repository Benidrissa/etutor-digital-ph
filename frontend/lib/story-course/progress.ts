/**
 * Where a learner is in a module story, kept in this browser (contract C-5).
 *
 * `sira.story.progress:{userId}:{storyId}` holds `{v: 1, completedUnits,
 * points}`, plus the chapter keys of the revision last read here
 * (`chapterKeys`, `revision`). It is per learner: the story id is the same for every learner of
 * the module, and a phone is often shared, so one learner must never resume
 * from (or be told they finished with) another's progress. Without a known
 * learner nothing is read or saved.
 * Progress is keyed by the chapter's module unit id, not by a chapter or step
 * index, so it survives the story being regenerated: a rewritten chapter of
 * the same unit is still done, and chapters keep their place when a unit is
 * added or renamed.
 *
 * This is a per-viewer convenience: storage can be missing, full or throw
 * (private mode, blocked site data), and then the story simply starts from
 * the first chapter. Lesson completion itself goes to the server.
 */

import type { Chapter } from "./types";

export interface StoryProgress {
  v: 1;
  /** module_unit_id of every chapter finished at least once. */
  completedUnits: string[];
  /** Best points per module_unit_id. */
  points: Record<string, number>;
  /**
   * The chapter keys of the story revision last opened here, and that
   * revision (#2682). `completedUnits` keeps keys of chapters a newer
   * revision dropped (a checkpoint replaced by the rally); the module page,
   * which never loads the story, counts only the keys of this snapshot, and
   * only while the server still serves the same revision.
   */
  chapterKeys?: string[];
  revision?: string;
}

const PREFIX = "sira.story.progress:";

export function storyProgressKey(storyId: string, userId: string): string {
  return `${PREFIX}${userId}:${storyId}`;
}

/**
 * The id the backend gives a module story (C-2's module_story_slug:
 * `module-{uuid hex}-{lang}`), so the module page can read progress before
 * it has the document.
 */
export function moduleStoryId(moduleId: string, language: "fr" | "en"): string {
  return `module-${moduleId.replace(/-/g, "").toLowerCase()}-${language}`;
}

/** C-2's namespace of a chapter-local id: `u{unit number, non-alphanumerics as _}-`. */
const CHAPTER_NAMESPACE = /^u[A-Za-z0-9_]+-(?=.)/;

/**
 * An id of a module story as its chapter wrote it, for display: the
 * assembler namespaces every chapter-local id (`u1_1-E1`), and a learner
 * should read `E1`. Only for module stories: an authored week's ids are its own.
 */
export function chapterLocalId(id: string): string {
  return id.replace(CHAPTER_NAMESPACE, "");
}

export function emptyStoryProgress(): StoryProgress {
  return { v: 1, completedUnits: [], points: {} };
}

/**
 * This learner's saved progress, or an empty one when there is none, it
 * cannot be read, or the learner is not known.
 */
export function readStoryProgress(
  storyId: string,
  userId: string | null | undefined,
): StoryProgress {
  if (!userId) return emptyStoryProgress();
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(storyProgressKey(storyId, userId));
  } catch {
    return emptyStoryProgress();
  }
  if (!raw) return emptyStoryProgress();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return emptyStoryProgress();
    const value = parsed as Record<string, unknown>;
    if (value.v !== 1) return emptyStoryProgress();
    const completedUnits = Array.isArray(value.completedUnits)
      ? [...new Set(value.completedUnits.filter((id): id is string => typeof id === "string"))]
      : [];
    const points: Record<string, number> = {};
    if (value.points && typeof value.points === "object") {
      for (const [key, score] of Object.entries(value.points as Record<string, unknown>)) {
        if (typeof score === "number" && Number.isFinite(score) && score >= 0) {
          points[key] = score;
        }
      }
    }
    const progress: StoryProgress = { v: 1, completedUnits, points };
    if (Array.isArray(value.chapterKeys) && typeof value.revision === "string" && value.revision) {
      progress.chapterKeys = [
        ...new Set(value.chapterKeys.filter((key): key is string => typeof key === "string")),
      ];
      progress.revision = value.revision;
    }
    return progress;
  } catch {
    return emptyStoryProgress();
  }
}

/**
 * The progress with a snapshot of the story revision being read: its
 * chapter keys and its revision. Unchanged (the same object) when the
 * snapshot is already there, so nothing needs writing.
 */
export function withChapterSnapshot(
  progress: StoryProgress,
  chapters: Chapter[],
  revision: string | null | undefined,
): StoryProgress {
  if (!revision) return progress;
  const chapterKeys = chapters.map(chapterKey);
  if (
    progress.revision === revision &&
    progress.chapterKeys?.length === chapterKeys.length &&
    progress.chapterKeys.every((key, index) => key === chapterKeys[index])
  ) {
    return progress;
  }
  return { ...progress, chapterKeys, revision };
}

/**
 * How far a learner is, from the module page's side (which has the status
 * route's revision and chapter count, never the story): finished chapters of
 * the snapshot when it is of the revision the server serves now. Without
 * one, the count of saved keys is only a hint: it may include stale keys, so
 * it never says the story is finished.
 */
export function storyStanding(
  progress: StoryProgress,
  status: { chapters: number | null; revision: string | null } | null,
): { completed: number; total: number; certain: boolean } {
  const total = Math.max(0, Number(status?.chapters ?? 0) || 0);
  if (progress.chapterKeys && progress.revision && status?.revision && progress.revision === status.revision) {
    const keys = new Set(progress.chapterKeys);
    const completed = progress.completedUnits.filter((key) => keys.has(key)).length;
    return { completed, total: progress.chapterKeys.length || total, certain: true };
  }
  return { completed: progress.completedUnits.length, total, certain: false };
}

/** Save this learner's progress; a storage failure only means it is not remembered. */
export function writeStoryProgress(
  storyId: string,
  userId: string | null | undefined,
  progress: StoryProgress,
): void {
  if (!userId) return;
  try {
    window.localStorage.setItem(storyProgressKey(storyId, userId), JSON.stringify(progress));
  } catch {
    // Not remembered; the story still plays for this visit.
  }
}

/**
 * The progress once the chapter of `unitKey` is finished with `points`. The
 * unit is listed once, and the best score is kept, so replaying a chapter
 * can only raise it.
 */
export function withChapterDone(
  progress: StoryProgress,
  unitKey: string,
  points: number,
): StoryProgress {
  const completedUnits = progress.completedUnits.includes(unitKey)
    ? progress.completedUnits
    : [...progress.completedUnits, unitKey];
  const best = Math.max(progress.points[unitKey] ?? 0, Math.max(0, points));
  return { ...progress, v: 1, completedUnits, points: { ...progress.points, [unitKey]: best } };
}

/**
 * The key a chapter's progress is stored under: its unit, else its own id.
 *
 * The rally (#2674) points at the same quiz unit the older quiz checkpoint
 * did, so it gets a key of its own: a learner who passed the checkpoint has
 * not played the rally. Lesson keys never change.
 */
export function chapterKey(chapter: Chapter): string {
  const covers = chapter.covers;
  if (covers?.rally) return `rally:${covers.module_unit_id}`;
  return covers?.module_unit_id ?? chapter.id;
}

/** Index of the first chapter not finished yet, or -1 when all are. */
export function firstIncompleteChapter(chapters: Chapter[], progress: StoryProgress): number {
  const done = new Set(progress.completedUnits);
  return chapters.findIndex((chapter) => !done.has(chapterKey(chapter)));
}

/** How many of `chapters` are finished. */
export function completedChapterCount(chapters: Chapter[], progress: StoryProgress): number {
  const done = new Set(progress.completedUnits);
  return chapters.filter((chapter) => done.has(chapterKey(chapter))).length;
}
