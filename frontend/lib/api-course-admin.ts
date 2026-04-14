/**
 * Shared API wrappers for admin course operations.
 * Used by both the Legacy wizard (CourseWizardClient) and the AI-Assisted wizard (AICourseWizard).
 */
import { apiFetch, API_BASE } from "@/lib/api";
import { authClient } from "@/lib/auth";

// ── Shared types ──────────────────────────────────────────────────────

export interface UploadedFile {
  name: string;
  size_bytes: number;
  status: "uploading" | "uploaded" | "error";
  error?: string;
}

export interface CourseInfo {
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
  course_domain: string[];
  course_level: string[];
  audience_type: string[];
  estimated_hours: number;
}

export interface GeneratedModule {
  id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
}

export interface TaskProgress {
  state: string;
  step?: string;
  step_label?: string;
  progress: number;
  files_total: number;
  files_processed: number;
  current_file?: string;
  chunks_processed: number;
  estimated_seconds_remaining?: number;
}

export interface IndexStatus {
  indexed: boolean;
  chunks_indexed: number;
  images_indexed?: number;
  task?: TaskProgress;
}

// ── Auth helper ───────────────────────────────────────────────────────

export async function getAuthHeaders(): Promise<Record<string, string>> {
  const token = await authClient.getValidToken();
  return { Authorization: `Bearer ${token}` };
}

// ── Course CRUD ───────────────────────────────────────────────────────

export async function createAdminCourse(data: {
  title_fr: string;
  title_en: string;
  description_fr?: string | null;
  description_en?: string | null;
  course_domain?: string[];
  course_level?: string[];
  audience_type?: string[];
  estimated_hours?: number;
  creation_mode?: string;
}): Promise<{ id: string; creation_step: string }> {
  return apiFetch("/api/v1/admin/courses", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateAdminCourse(
  courseId: string,
  data: Record<string, unknown>
): Promise<void> {
  await apiFetch(`/api/v1/admin/courses/${courseId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function getAdminCourse(courseId: string) {
  return apiFetch<{
    title_fr: string;
    title_en: string;
    description_fr: string | null;
    description_en: string | null;
    course_domain: string[];
    course_level: string[];
    audience_type: string[];
    estimated_hours: number;
    creation_mode: string;
  }>(`/api/v1/admin/courses/${courseId}`);
}

// ── Resource upload ───────────────────────────────────────────────────

export async function uploadCourseResource(
  courseId: string,
  file: File
): Promise<{ ok: boolean; error?: string }> {
  const headers = await getAuthHeaders();
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(
    `${API_BASE}/api/v1/admin/courses/${courseId}/resources`,
    { method: "POST", headers, body: formData }
  );

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    return { ok: false, error: body?.detail || "Upload failed" };
  }
  return { ok: true };
}

export async function deleteCourseResource(
  courseId: string,
  filename: string
): Promise<void> {
  const headers = await getAuthHeaders();
  await fetch(
    `${API_BASE}/api/v1/admin/courses/${courseId}/resources/${encodeURIComponent(filename)}`,
    { method: "DELETE", headers }
  ).catch(() => {});
}

export async function getCourseResources(
  courseId: string
): Promise<{ files: Array<{ name: string; size_bytes: number }> }> {
  return apiFetch(`/api/v1/admin/courses/${courseId}/resources`);
}

// ── Syllabus generation ───────────────────────────────────────────────

export async function triggerSyllabusGeneration(
  courseId: string,
  estimatedHours: number,
  force?: boolean
): Promise<{ task_id: string; status: string }> {
  const url = `/api/v1/admin/courses/${courseId}/generate-structure${force ? "?force=true" : ""}`;
  return apiFetch(url, {
    method: "POST",
    body: JSON.stringify({ estimated_hours: estimatedHours }),
  });
}

export async function regenerateSyllabusApi(
  courseId: string,
  mode: "reuse" | "fresh"
): Promise<{ task_id: string; status: string }> {
  return apiFetch(
    `/api/v1/admin/courses/${courseId}/regenerate-syllabus?mode=${mode}`,
    { method: "POST" }
  );
}

export async function getGenerationStatus(courseId: string, taskId?: string) {
  const params = taskId ? `?task_id=${taskId}` : "";
  return apiFetch<{
    has_modules: boolean;
    modules_count: number;
    creation_step?: string;
    modules?: GeneratedModule[];
    task?: { id?: string; state: string; meta?: Record<string, unknown> };
  }>(`/api/v1/admin/courses/${courseId}/generate-status${params}`);
}

// ── RAG indexation ────────────────────────────────────────────────────

export async function triggerIndexation(
  courseId: string
): Promise<{ task_id: string; status: string }> {
  return apiFetch(`/api/v1/admin/courses/${courseId}/index-resources`, {
    method: "POST",
  });
}

export async function getIndexStatusApi(courseId: string, taskId?: string) {
  const params = taskId ? `?task_id=${taskId}` : "";
  return apiFetch<{
    indexed: boolean;
    chunks_indexed: number;
    images_indexed?: number;
    creation_step?: string;
    task?: TaskProgress & { id?: string; state: string };
  }>(`/api/v1/admin/courses/${courseId}/index-status${params}`);
}

export async function cancelIndexationApi(courseId: string): Promise<void> {
  await apiFetch(`/api/v1/admin/courses/${courseId}/cancel-indexation`, {
    method: "POST",
  });
}

export async function reindexImagesApi(
  courseId: string
): Promise<{ task_id: string; status: string }> {
  return apiFetch(`/api/v1/admin/courses/${courseId}/reindex-images`, {
    method: "POST",
  });
}

// ── AI metadata suggestion ────────────────────────────────────────────

export interface SuggestedMetadata {
  title_fr: string;
  title_en: string;
  description_fr: string;
  description_en: string;
}

export async function suggestCourseMetadata(
  courseId: string
): Promise<SuggestedMetadata> {
  return apiFetch(`/api/v1/admin/courses/${courseId}/suggest-metadata`, {
    method: "POST",
  });
}

// ── Publishing ────────────────────────────────────────────────────────

export async function publishAdminCourse(courseId: string): Promise<void> {
  await apiFetch(`/api/v1/admin/courses/${courseId}/publish`, {
    method: "POST",
  });
}

// ── Utilities ─────────────────────────────────────────────────────────

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
