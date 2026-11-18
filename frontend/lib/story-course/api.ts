/**
 * API client for story-course weeks.
 *
 * A week is fetched whole and cached, because the player is expected to run
 * with no network once a week is open (the platform targets 2G/3G phones).
 */

import { apiFetch } from "../api";
import type {
  ModuleStoryStatus,
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
 * The 202 envelope a story answers with while it is being written.
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
 * The path of one module's story (contract C-5, served per C-4). A GET is
 * gated (subscribers and admins, or a module whose units are all free) and
 * generates the story on first access: 200 with the document, 202 with
 * {@link StoryGenerating} while its chapters are written, 409
 * `story_unavailable` when no valid story could be assembled, 403
 * `subscription_required` behind the paywall.
 *
 * `generate: false` only reads the cache: a story nobody has opened yet
 * answers 404 `story_not_cached` and nothing is dispatched. The module
 * downloader uses it so a download never pays for a story.
 *
 * Kept here so the story page (through loadModuleStory) and the module
 * downloader request the very same URL.
 */
export function moduleStoryPath(
  moduleId: string,
  language: "fr" | "en",
  options: { generate?: boolean } = {},
): string {
  return (
    `/api/v1/story-courses/module/${encodeURIComponent(moduleId)}?language=${language}` +
    (options.generate === false ? "&generate=false" : "")
  );
}

/**
 * The path of a module story's status (contract C-4). It never dispatches,
 * so the module page can show the story card's state without downloading
 * the story.
 */
export function moduleStoryStatusPath(moduleId: string, language: "fr" | "en"): string {
  return (
    `/api/v1/story-courses/module/${encodeURIComponent(moduleId)}/status` +
    `?language=${language}`
  );
}

/** A module story's state, for the story card on the module page. */
export async function getModuleStoryStatus(
  moduleId: string,
  language: "fr" | "en",
): Promise<ModuleStoryStatus> {
  return apiFetch<ModuleStoryStatus>(moduleStoryStatusPath(moduleId, language));
}

/**
 * The machine-readable code in a story endpoint's error body
 * (`{"detail": {"error": "..."}}`), whatever the HTTP status. Clients map on
 * this, not on the status (contract X2): story mode switched off is a 404
 * `story_mode_disabled`, not a 403.
 */
export function storyErrorCode(err: unknown): string | undefined {
  if (!err || typeof err !== "object") return undefined;
  const detail = (err as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return undefined;
  const code = (detail as { error?: unknown }).error;
  return typeof code === "string" ? code : undefined;
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

/** The 409 a story endpoint sends when no valid story could be generated. */
export function isStoryUnavailableError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  if ((err as { status?: unknown }).status !== 409) return false;
  // A 409 carrying some other error code goes down the generic failure path,
  // so a future, different conflict is not mistaken for "no story".
  const code = storyErrorCode(err);
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

export type { ModuleStoryStatus, StoryCourse, StoryCourseListItem };
