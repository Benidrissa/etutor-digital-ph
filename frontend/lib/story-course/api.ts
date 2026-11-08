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
