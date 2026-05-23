/**
 * API client for course bundle (ZIP export) operations.
 */
import { API_BASE, apiFetch } from "@/lib/api";
import { getAuthHeaders } from "@/lib/api-course-admin";

export type BundleStatus = "pending" | "generating" | "ready" | "failed";

export interface BundleCreatedResponse {
  bundle_id: string;
  task_id: string;
  status: string;
}

export interface BundleStatusResponse {
  bundle_id: string;
  status: BundleStatus;
  progress: number | null;
  current_file: string | null;
  download_url: string | null;
  file_count: number | null;
  file_size_bytes: number | null;
  error_message: string | null;
}

export interface BundleListItem {
  bundle_id: string;
  course_id: string;
  course_title: string;
  language: string;
  level: number;
  status: BundleStatus;
  file_count: number | null;
  file_size_bytes: number | null;
  created_at: string;
  completed_at: string | null;
  download_url: string | null;
  error_message: string | null;
}

export interface BundleCreatePayload {
  language: "fr" | "en";
  level?: number;
  country?: string;
}

export async function createCourseBundle(
  courseId: string,
  payload: BundleCreatePayload,
): Promise<BundleCreatedResponse> {
  return apiFetch<BundleCreatedResponse>(
    `/api/v1/admin/courses/${courseId}/bundle`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export async function getCourseBundleStatus(
  courseId: string,
  bundleId: string,
): Promise<BundleStatusResponse> {
  return apiFetch<BundleStatusResponse>(
    `/api/v1/admin/courses/${courseId}/bundle/status?bundle_id=${bundleId}`,
  );
}

export async function listBundles(params?: {
  course_id?: string;
  bundle_status?: string;
  limit?: number;
}): Promise<BundleListItem[]> {
  const qs = new URLSearchParams();
  if (params?.course_id) qs.set("course_id", params.course_id);
  if (params?.bundle_status) qs.set("bundle_status", params.bundle_status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<BundleListItem[]>(`/api/v1/admin/bundles${suffix}`);
}

export async function downloadBundle(
  bundleId: string,
  filename: string,
): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/v1/admin/bundles/${bundleId}/download`, {
    headers,
  });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export async function deleteBundle(bundleId: string): Promise<void> {
  await apiFetch(`/api/v1/admin/bundles/${bundleId}`, { method: "DELETE" });
}
