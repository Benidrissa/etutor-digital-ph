/**
 * API client for story-course weeks.
 *
 * A week is fetched whole and cached, because the player is expected to run
 * with no network once a week is open (the platform targets 2G/3G phones).
 */

import { apiFetch } from "../api";
import type {
  StoryCourse,
  StoryCourseListItem,
  StoryCourseListResponse,
} from "./types";

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  path: string;
  message: string;
}

export interface ValidationReport {
  ok: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  checks: Record<string, unknown>;
}

/** The weeks the app lists. */
export async function listStoryCourses(options?: {
  courseId?: string;
  week?: number;
  includeDrafts?: boolean;
  page?: number;
  limit?: number;
}): Promise<StoryCourseListResponse> {
  const params = new URLSearchParams();
  if (options?.courseId) params.set("course_id", options.courseId);
  if (options?.week !== undefined) params.set("week", String(options.week));
  if (options?.includeDrafts) params.set("include_drafts", "true");
  if (options?.page) params.set("page", String(options.page));
  if (options?.limit) params.set("limit", String(options.limit));
  const query = params.toString();
  return apiFetch<StoryCourseListResponse>(
    `/api/v1/story-courses${query ? `?${query}` : ""}`,
  );
}

/** One week, whole. */
export async function getStoryCourse(slug: string): Promise<StoryCourse> {
  return apiFetch<StoryCourse>(`/api/v1/story-courses/${encodeURIComponent(slug)}`);
}

/**
 * The 202 envelope a lesson story answers with while it is being written.
 *
 * Same shape as lessons and quizzes, so the client polls the shared
 * `GET /api/v1/content/status/{task_id}` exactly as it does for them.
 */
export interface StoryGenerating {
  status: "generating";
  task_id: string;
  message?: string;
}

/**
 * The path of one lesson's story (contract C3). A GET is learner-readable and
 * generates the story on first access: 200 with the document, 202 with
 * {@link StoryGenerating}, or 409 `story_unavailable` when the generator could
 * not produce a week that passes the validator.
 *
 * Kept here so the lesson panel (through the offline loader) and the module
 * downloader request the very same URL.
 */
export function unitStoryPath(
  moduleId: string,
  unitId: string,
  language: "fr" | "en",
): string {
  return (
    `/api/v1/story-courses/unit/${encodeURIComponent(moduleId)}` +
    `/${encodeURIComponent(unitId)}?language=${language}`
  );
}

/** True for the 202 "still writing it" envelope. */
export function isStoryGenerating(value: unknown): value is StoryGenerating {
  return (
    !!value &&
    typeof value === "object" &&
    (value as { status?: unknown }).status === "generating"
  );
}

/**
 * True when `value` looks like a story document rather than an envelope or an
 * error body — the guard that keeps a stray 202 from reaching the player (the
 * lesson viewer white-screened on exactly that once).
 */
export function isStoryDocument(value: unknown): value is StoryCourse {
  return (
    !!value &&
    typeof value === "object" &&
    Array.isArray((value as { chapters?: unknown }).chapters) &&
    !!(value as { languages?: unknown }).languages
  );
}

/** The 409 the unit endpoint sends when no valid story could be generated. */
export function isStoryUnavailableError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const { status, detail } = err as { status?: unknown; detail?: unknown };
  if (status !== 409) return false;
  // A 409 carrying some other error code goes down the generic failure path,
  // so a future, different conflict is not mistaken for "no story".
  const code =
    detail && typeof detail === "object" ? (detail as { error?: unknown }).error : undefined;
  return code === undefined || code === "story_unavailable";
}

/** Run the Appendix C checks on an authored file without saving it. */
export async function validateStoryCourse(
  content: unknown,
): Promise<ValidationReport> {
  return apiFetch<ValidationReport>("/api/v1/story-courses/validate", {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export type { StoryCourse, StoryCourseListItem };
