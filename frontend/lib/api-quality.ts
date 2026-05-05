import { apiFetch } from "./api";

export type QualityStatus =
  | "pending"
  | "scoring"
  | "passing"
  | "needs_review"
  | "regenerating"
  | "needs_review_final"
  | "manual_override"
  | "failed";

export type RunStatus =
  | "queued"
  | "scoring"
  | "regenerating"
  | "completed"
  | "failed"
  | "cancelled";

export type RunKind = "full" | "targeted" | "glossary_only";

export type FlagCategory =
  | "terminology_drift"
  | "ungrounded_claim"
  | "syllabus_scope_drift"
  | "internal_contradiction"
  | "pedagogical_mismatch"
  | "structural_gap";

export type FlagSeverity = "low" | "medium" | "high" | "blocking";

export type DimensionKey =
  | "terminology_consistency"
  | "source_grounding"
  | "syllabus_alignment"
  | "internal_contradictions"
  | "pedagogical_fit"
  | "structural_completeness";

export const DIMENSION_KEYS: DimensionKey[] = [
  "terminology_consistency",
  "source_grounding",
  "syllabus_alignment",
  "internal_contradictions",
  "pedagogical_fit",
  "structural_completeness",
];

export const DIMENSION_WEIGHTS: Record<DimensionKey, number> = {
  terminology_consistency: 25,
  source_grounding: 20,
  syllabus_alignment: 20,
  internal_contradictions: 15,
  pedagogical_fit: 10,
  structural_completeness: 10,
};

export interface QualityFlag {
  category: FlagCategory;
  severity: FlagSeverity;
  location: string;
  description: string;
  evidence: string;
  suggested_fix: string;
  evidence_unit_id: string | null;
}

export type DimensionScores = Record<DimensionKey, number>;

export interface CourseQualityRunSummary {
  id: string;
  course_id: string;
  run_kind: RunKind;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  overall_score: number | null;
  units_total: number;
  units_passing: number;
  units_regenerated: number;
  budget_credits: number;
  spent_credits: number;
  triggered_by_user_id: string | null;
  notes: string | null;
  created_at: string;
}

export interface UnitQualitySummary {
  generated_content_id: string;
  unit_number: string | null;
  content_type: string;
  language: string;
  quality_score: number | null;
  quality_status: QualityStatus;
  flag_count: number;
  regeneration_attempts: number;
  is_manually_edited: boolean;
  last_assessed_at: string | null;
}

export interface CourseQualityRunDetail extends CourseQualityRunSummary {
  units: UnitQualitySummary[];
}

export interface UnitQualityDetail {
  generated_content_id: string;
  unit_number: string | null;
  content_type: string;
  language: string;
  quality_score: number | null;
  quality_status: QualityStatus;
  flag_count: number;
  regeneration_attempts: number;
  is_manually_edited: boolean;
  validated: boolean;
  quality_assessed_at: string | null;
  last_quality_run_id: string | null;
  quality_flags: QualityFlag[];
  dimension_scores: DimensionScores | null;
  latest_attempt_id: string | null;
  latest_attempt_number: number | null;
  latest_attempt_score: number | null;
}

export interface GlossaryEntryResponse {
  id: string;
  term_display: string;
  language: string;
  canonical_definition: string;
  first_unit_number: string | null;
  consistency_status: "consistent" | "drift_detected" | "unsourced";
  drift_details: string | null;
  occurrences_count: number;
  status: string;
}

export interface QualitySummary {
  course_id: string;
  units_total: number;
  units_by_status: Partial<Record<QualityStatus, number>>;
  glossary_drift_count: number;
  last_run: CourseQualityRunSummary | null;
}

export interface ReviewQueueEntry {
  course_id: string;
  course_title_fr: string;
  course_title_en: string;
  owner_id: string | null;
  units_total: number;
  units_passing: number;
  units_needs_review: number;
  units_needs_review_final: number;
  units_failed: number;
  glossary_drift_count: number;
  last_assessed_at: string | null;
  last_run: CourseQualityRunSummary | null;
}

// ---- read endpoints ----

export function getQualitySummary(courseId: string): Promise<QualitySummary> {
  return apiFetch<QualitySummary>(
    `/api/v1/admin/courses/${courseId}/quality/summary`,
  );
}

export function listQualityRuns(
  courseId: string,
  limit = 20,
): Promise<CourseQualityRunSummary[]> {
  return apiFetch<CourseQualityRunSummary[]>(
    `/api/v1/admin/courses/${courseId}/quality/runs?limit=${limit}`,
  );
}

export function getQualityRun(
  courseId: string,
  runId: string,
): Promise<CourseQualityRunDetail> {
  return apiFetch<CourseQualityRunDetail>(
    `/api/v1/admin/courses/${courseId}/quality/runs/${runId}`,
  );
}

export function getCourseGlossary(
  courseId: string,
  language?: string,
): Promise<GlossaryEntryResponse[]> {
  const qs = language ? `?language=${encodeURIComponent(language)}` : "";
  return apiFetch<GlossaryEntryResponse[]>(
    `/api/v1/admin/courses/${courseId}/quality/glossary${qs}`,
  );
}

export function getUnitQualityDetail(
  courseId: string,
  contentId: string,
): Promise<UnitQualityDetail> {
  return apiFetch<UnitQualityDetail>(
    `/api/v1/admin/courses/${courseId}/units/${contentId}/quality`,
  );
}

export function getReviewQueue(opts?: {
  hasIssues?: boolean;
  limit?: number;
}): Promise<ReviewQueueEntry[]> {
  const params = new URLSearchParams();
  if (opts?.hasIssues !== undefined) {
    params.set("has_issues", String(opts.hasIssues));
  }
  if (opts?.limit !== undefined) {
    params.set("limit", String(opts.limit));
  }
  const qs = params.toString();
  return apiFetch<ReviewQueueEntry[]>(
    `/api/v1/admin/quality/review-queue${qs ? `?${qs}` : ""}`,
  );
}

// ---- run-state helpers ----

const ACTIVE_RUN_STATUSES: ReadonlySet<RunStatus> = new Set([
  "queued",
  "scoring",
  "regenerating",
]);

export function isRunInProgress(status: RunStatus | null | undefined): boolean {
  return status !== null && status !== undefined && ACTIVE_RUN_STATUSES.has(status);
}

export const FLAGGED_STATUSES: ReadonlySet<QualityStatus> = new Set([
  "needs_review",
  "needs_review_final",
  "failed",
]);
