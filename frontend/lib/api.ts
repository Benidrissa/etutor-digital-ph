import type { Branding } from "./branding";
import { DEFAULT_BRANDING } from "./branding";

/**
 * API_BASE resolves to:
 * - Server-side (SSR): BACKEND_URL for direct container-to-container calls.
 * - Client-side (browser): empty string — calls go to the same Next.js origin
 *   and next.config.ts rewrites `/api/*` to BACKEND_URL. Keeps one image
 *   portable across envs (#1742).
 */
export const API_BASE =
  typeof window === "undefined"
    ? process.env.BACKEND_URL || "http://localhost:8000"
    : "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// Course Taxonomy Types (DB-driven, no hardcoded enums)
export interface TaxonomyItem {
  value: string;
  label_fr: string;
  label_en: string;
}

export interface TaxonomyResponse {
  domains: TaxonomyItem[];
  levels: TaxonomyItem[];
  audience_types: TaxonomyItem[];
}

export interface TaxonomyCategoryAdmin {
  id: string;
  type: string;
  slug: string;
  label_fr: string;
  label_en: string;
  sort_order: number;
  is_active: boolean;
}

export interface TaxonomyAdminResponse {
  domains: TaxonomyCategoryAdmin[];
  levels: TaxonomyCategoryAdmin[];
  audience_types: TaxonomyCategoryAdmin[];
}

// Course Catalog API Types
export interface CourseResponse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  course_domain: TaxonomyItem[];
  course_level: TaxonomyItem[];
  audience_type: TaxonomyItem[];
  estimated_hours: number;
  module_count: number;
  cover_image_url?: string;
  is_published: boolean;
  enrolled: boolean;
}

export interface EnrollmentResponse {
  course_id: string;
  user_id: string;
  enrolled_at: string;
  status: "active" | "completed" | "dropped";
}

export interface CourseWithEnrollment extends CourseResponse {
  enrollment?: EnrollmentResponse;
}

export async function getCourseTaxonomy(): Promise<TaxonomyResponse> {
  return apiFetch<TaxonomyResponse>("/api/v1/courses/taxonomy");
}

export async function getCourses(filters?: {
  course_domain?: string;
  course_level?: string;
  audience_type?: string;
  search?: string;
  curriculum?: string;
}): Promise<CourseResponse[]> {
  const params = new URLSearchParams();
  if (filters?.course_domain)
    params.set("course_domain", filters.course_domain);
  if (filters?.course_level) params.set("course_level", filters.course_level);
  if (filters?.audience_type)
    params.set("audience_type", filters.audience_type);
  if (filters?.search) params.set("search", filters.search);
  if (filters?.curriculum) params.set("curriculum", filters.curriculum);
  const qs = params.toString();
  return apiFetch<CourseResponse[]>(`/api/v1/courses${qs ? `?${qs}` : ""}`);
}

export async function enrollInCourse(
  courseId: string,
): Promise<EnrollmentResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<EnrollmentResponse>(
    `/api/v1/courses/${courseId}/enroll`,
    { method: "POST" },
  );
}

// Admin Taxonomy API
export async function getAdminTaxonomy(): Promise<TaxonomyAdminResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<TaxonomyAdminResponse>(
    "/api/v1/admin/taxonomy",
  );
}

export async function createTaxonomyCategory(data: {
  type: string;
  slug: string;
  label_fr: string;
  label_en: string;
  sort_order?: number;
}): Promise<TaxonomyCategoryAdmin> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<TaxonomyCategoryAdmin>(
    "/api/v1/admin/taxonomy",
    { method: "POST", body: JSON.stringify(data) },
  );
}

export async function updateTaxonomyCategory(
  id: string,
  data: Partial<{
    label_fr: string;
    label_en: string;
    sort_order: number;
    is_active: boolean;
  }>,
): Promise<TaxonomyCategoryAdmin> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<TaxonomyCategoryAdmin>(
    `/api/v1/admin/taxonomy/${id}`,
    { method: "PATCH", body: JSON.stringify(data) },
  );
}

export async function deleteTaxonomyCategory(id: string): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(`/api/v1/admin/taxonomy/${id}`, {
    method: "DELETE",
  });
}

export async function getMyEnrollments(opts?: {
  orderBy?: "last_accessed";
  limit?: number;
}): Promise<CourseWithEnrollment[]> {
  const { authClient } = await import("./auth");
  const params = new URLSearchParams();
  if (opts?.orderBy) params.set("order_by", opts.orderBy);
  if (opts?.limit) params.set("limit", String(opts.limit));
  const qs = params.toString();
  return authClient.authenticatedFetch<CourseWithEnrollment[]>(
    `/api/v1/courses/my-enrollments${qs ? `?${qs}` : ""}`,
  );
}

// Progress API Types
export interface ModuleProgressResponse {
  module_id: string;
  user_id: string;
  module_number: number | null;
  title_fr: string;
  title_en: string;
  description_fr?: string | null;
  description_en?: string | null;
  level: number;
  estimated_hours: number;
  status: "locked" | "in_progress" | "completed";
  completion_pct: number;
  quiz_score_avg: number | null;
  time_spent_minutes: number;
  last_accessed: string | null;
}

export interface UnitProgressDetail {
  id: string;
  unit_number: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  estimated_minutes: number;
  order_index: number;
  unit_type?: "lesson" | "quiz" | "case-study";
  status: "pending" | "in_progress" | "completed";
}

export interface ModuleDetailWithProgressResponse {
  id: string;
  module_number: number;
  level: number;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  estimated_hours: number;
  prereq_modules: string[];
  status: "locked" | "in_progress" | "completed";
  completion_pct: number;
  quiz_score_avg: number | null;
  time_spent_minutes: number;
  last_accessed: string | null;
  units: UnitProgressDetail[];
}

export interface LessonAccessRequest {
  module_id: string;
  lesson_id: string;
  time_spent_seconds?: number;
  completion_percentage?: number;
}

// Progress API Functions
export async function getModuleProgress(
  moduleId: string,
): Promise<ModuleProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleProgressResponse>(
    `/api/v1/progress/modules/${moduleId}`,
  );
}

export async function getAllModuleProgress(
  courseId?: string,
): Promise<ModuleProgressResponse[]> {
  const { authClient } = await import("./auth");
  const url = courseId
    ? `/api/v1/progress/modules?course_id=${encodeURIComponent(courseId)}`
    : "/api/v1/progress/modules";
  return authClient.authenticatedFetch<ModuleProgressResponse[]>(url);
}

export async function getModuleDetailWithProgress(
  moduleId: string,
): Promise<ModuleDetailWithProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleDetailWithProgressResponse>(
    `/api/v1/progress/modules/${moduleId}/detail`,
  );
}

export interface PublicUnitDetail {
  id: string;
  unit_number: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  estimated_minutes: number;
  order_index: number;
  unit_type?: "lesson" | "quiz" | "case-study";
}

export interface ModuleUnitsResponse {
  module_id: string;
  module_number: number;
  level: number;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  estimated_hours: number;
  bloom_level?: string;
  learning_objectives_fr?: string[];
  learning_objectives_en?: string[];
  units: PublicUnitDetail[];
}

export async function getModuleUnits(
  moduleId: string,
): Promise<ModuleUnitsResponse> {
  return apiFetch<ModuleUnitsResponse>(
    `/api/v1/content/modules/${moduleId}/units`,
  );
}

export async function trackLessonAccess(
  request: LessonAccessRequest,
): Promise<ModuleProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleProgressResponse>(
    "/api/v1/progress/lesson-access",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };

  if (typeof window !== "undefined") {
    try {
      const { authClient } = await import("./auth");
      const token = await authClient.getValidToken();
      headers["Authorization"] = `Bearer ${token}`;
    } catch {
      // No valid token — proceed without auth header (unauthenticated call)
    }
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!res.ok) {
    let message = `API error: ${res.status}`;
    let code: string | undefined;
    try {
      const body = await res.json();
      if (body?.detail?.message) message = body.detail.message;
      else if (typeof body?.detail === "string") message = body.detail;
      if (body?.detail?.code) code = body.detail.code;
    } catch {
      // ignore parse errors — keep the status-code message
    }
    throw new ApiError(message, res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Alias for backward compatibility and common usage
export const fetchApi = apiFetch;

// Lesson Image API Types
export type LessonImageStatus = "pending" | "generating" | "ready" | "failed";

export interface LessonImageResponse {
  lesson_id: string;
  status: LessonImageStatus;
  url?: string;
  alt_text?: string;
  alt_text_fr?: string;
  alt_text_en?: string;
}

interface _ApiLessonImage {
  image_id: string;
  lesson_id: string;
  status: LessonImageStatus;
  image_url: string | null;
  alt_text: string;
  format: string;
  width: number;
}

interface _ApiLessonImagesListResponse {
  lesson_id: string;
  images: _ApiLessonImage[];
  total: number;
}

export async function getLessonImageStatus(
  lessonId: string,
): Promise<LessonImageResponse> {
  const data = await apiFetch<_ApiLessonImagesListResponse>(
    `/api/v1/images/lesson/${lessonId}`,
  );
  const first = data.images[0];
  if (!first) {
    return { lesson_id: lessonId, status: "pending" };
  }
  return {
    lesson_id: first.lesson_id,
    status: first.status,
    url: first.image_url ?? undefined,
    alt_text: first.alt_text,
    alt_text_fr: first.alt_text,
    alt_text_en: first.alt_text,
  };
}

// Lesson Audio API Types
export type LessonAudioStatus = "pending" | "generating" | "ready" | "failed";

export interface LessonAudioResponse {
  lesson_id: string;
  status: LessonAudioStatus;
  url?: string;
  duration_seconds?: number;
}

interface _ApiLessonAudio {
  audio_id: string;
  lesson_id: string;
  status: LessonAudioStatus;
  audio_url: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
}

interface _ApiLessonAudioListResponse {
  lesson_id: string;
  audio: _ApiLessonAudio[];
  total: number;
}

export async function getLessonAudioStatus(
  lessonId: string,
): Promise<LessonAudioResponse> {
  const data = await apiFetch<_ApiLessonAudioListResponse>(
    `/api/v1/audio/lesson/${lessonId}`,
  );
  const first = data.audio[0];
  if (!first) {
    return { lesson_id: lessonId, status: "pending" };
  }
  return {
    lesson_id: first.lesson_id,
    status: first.status,
    url: first.audio_url ?? undefined,
    duration_seconds: first.duration_seconds ?? undefined,
  };
}

export interface DashboardStats {
  streak_days: number;
  average_quiz_score: number;
  total_time_studied_this_week: number;
  is_active_today: boolean;
  next_review_count: number;
  modules_in_progress: number;
  completion_percentage: number;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const { authClient } = await import("./auth");

  // Get user's timezone offset for accurate streak calculations
  const timezoneOffset = -new Date().getTimezoneOffset() / 60; // Convert to hours
  const offsetString =
    timezoneOffset >= 0
      ? `+${timezoneOffset.toString().padStart(2, "0")}:00`
      : `${timezoneOffset.toString().padStart(3, "0")}:00`;

  return authClient.authenticatedFetch<DashboardStats>(
    "/api/v1/dashboard/stats",
    {
      headers: {
        "X-Timezone-Offset": offsetString,
      },
    },
  );
}

export interface UpcomingReviewSession {
  date: string;
  module_name: string;
  card_count: number;
  is_overdue: boolean;
}

export interface UpcomingReviewsResponse {
  user_id: string;
  today_due_count: number;
  has_due_cards: boolean;
  upcoming_sessions: UpcomingReviewSession[];
}

export async function getUpcomingReviews(): Promise<UpcomingReviewsResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<UpcomingReviewsResponse>(
    "/api/v1/flashcards/upcoming",
  );
}

export interface FlashcardSetResponse {
  module_id: string;
  language: string;
  level: number;
  cards: unknown[];
  total_cards: number;
  cached: boolean;
}

export async function generateModuleFlashcards(params: {
  moduleId: string;
  language: string;
  level?: number;
}): Promise<FlashcardSetResponse> {
  const { authClient } = await import("./auth");
  const level = params.level ?? 1;
  return authClient.authenticatedFetch<FlashcardSetResponse>(
    `/api/v1/flashcards/modules/${params.moduleId}?language=${params.language}&level=${level}`,
  );
}

// Quiz API Types
export interface QuizQuestion {
  id: string;
  question: string;
  options: string[];
  correct_answer: number;
  explanation: string;
  sources_cited: string[];
  difficulty: string;
}

export interface QuizContent {
  title: string;
  description: string;
  questions: QuizQuestion[];
  time_limit_minutes?: number;
  passing_score: number;
}

export interface Quiz {
  id: string;
  module_id: string;
  unit_id: string;
  language: string;
  level: number;
  country_context: string;
  content: QuizContent;
  generated_at: string;
  cached: boolean;
  country_fallback?: boolean;
}

export interface QuizAnswerSubmission {
  question_id: string;
  selected_option: number;
  time_taken_seconds: number;
}

export interface QuizAttemptRequest {
  quiz_id: string;
  answers: QuizAnswerSubmission[];
  total_time_seconds: number;
}

export interface QuizAttemptResult {
  question_id: string;
  user_answer: number;
  correct_answer: number;
  is_correct: boolean;
  explanation: string;
  time_taken_seconds: number;
}

export interface QuizAttemptResponse {
  attempt_id: string;
  quiz_id: string;
  score: number;
  total_questions: number;
  correct_answers: number;
  total_time_seconds: number;
  passed: boolean;
  lesson_validated: boolean;
  results: QuizAttemptResult[];
  attempted_at: string;
}

// Quiz API Functions
export async function generateQuiz(params: {
  module_id: string;
  unit_id: string;
  language: string;
  country: string;
  level: number;
  num_questions?: number;
  force_regenerate?: boolean;
}): Promise<Quiz> {
  return apiFetch<Quiz>("/api/v1/quiz/generate", {
    method: "POST",
    body: JSON.stringify({
      module_id: params.module_id,
      unit_id: params.unit_id,
      language: params.language,
      country: params.country,
      level: params.level,
      num_questions: params.num_questions || 10,
      force_regenerate: params.force_regenerate || false,
    }),
  });
}

export async function getQuiz(quizId: string): Promise<Quiz> {
  return apiFetch<Quiz>(`/api/v1/quiz/${quizId}`);
}

export async function submitQuizAttempt(
  request: QuizAttemptRequest,
): Promise<QuizAttemptResponse> {
  return apiFetch<QuizAttemptResponse>("/api/v1/quiz/attempt", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

// Summative Assessment API Types
export interface SummativeAssessmentAttemptCheck {
  can_attempt: boolean;
  last_attempt_score?: number;
  attempt_count: number;
  next_retry_at?: string;
  reason?: string;
}

export interface SummativeAssessmentResponse {
  attempt_id: string;
  assessment_id: string;
  score: number;
  total_questions: number;
  correct_answers: number;
  total_time_seconds: number;
  passed: boolean;
  results: QuizAttemptResult[];
  domain_breakdown: Record<string, { correct: number; total: number }>;
  module_unlocked: boolean;
  can_retry: boolean;
  next_retry_at?: string;
  attempt_count: number;
  attempted_at: string;
}

// Unit Quiz Validation
export interface UnitQuizValidationStatus {
  passed: boolean;
  best_score: number | null;
  attempt_count: number;
}

export async function checkUnitQuizPassed(
  moduleId: string,
  unitId: string,
): Promise<UnitQuizValidationStatus> {
  return apiFetch<UnitQuizValidationStatus>(
    `/api/v1/quiz/attempts/status?module_id=${encodeURIComponent(moduleId)}&unit_id=${encodeURIComponent(unitId)}`,
  );
}

// Summative Assessment API Functions
export async function generateSummativeAssessment(params: {
  module_id: string;
  language: string;
  country: string;
  level: number;
}): Promise<Quiz> {
  return apiFetch<Quiz>("/api/v1/quiz/summative/generate", {
    method: "POST",
    body: JSON.stringify({
      module_id: params.module_id,
      language: params.language,
      country: params.country,
      level: params.level,
      num_questions: 20, // Always 20 for summative
    }),
  });
}

export async function canAttemptSummativeAssessment(
  moduleId: string,
): Promise<SummativeAssessmentAttemptCheck> {
  return apiFetch<SummativeAssessmentAttemptCheck>(
    `/api/v1/quiz/summative/${moduleId}/can-attempt`,
  );
}

export async function submitSummativeAssessmentAttempt(
  request: QuizAttemptRequest,
): Promise<SummativeAssessmentResponse> {
  return apiFetch<SummativeAssessmentResponse>(
    "/api/v1/quiz/summative/attempt",
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

// ── Source Image (PDF extraction) API ─────────────────────────

export interface SourceImageMeta {
  id: string;
  figure_number?: string;
  caption?: string;
  caption_fr?: string;
  caption_en?: string;
  attribution?: string;
  image_type?: string;
  alt_text_fr?: string;
  alt_text_en?: string;
}

export interface LessonResponse {
  id: string;
  module_id: string;
  unit_id: string;
  language: "fr" | "en";
  level: number;
  country_context: string;
  content: {
    introduction: string;
    concepts: string[];
    aof_example: string;
    synthesis: string;
    key_points: string[];
    sources_cited: string[];
  };
  cached: boolean;
  source_image_refs?: SourceImageMeta[];
}

// ── Lesson Video API (#1802) ─────────────────────────────────
// Per-lesson HeyGen video summaries, scoped the same way lesson
// audio is (``module_id + unit_id + language``). Admin or learner
// can trigger generation; the poller finalises the row when HeyGen
// finishes rendering (~10 min P50).

export type LessonVideoStatus = "pending" | "generating" | "ready" | "failed";

export interface LessonVideoResponse {
  lesson_id: string;
  video_id?: string;
  status: LessonVideoStatus;
  url?: string;
  duration_seconds?: number;
}

interface _ApiLessonVideo {
  video_id: string;
  lesson_id: string;
  status: LessonVideoStatus;
  video_url: string | null;
  duration_seconds: number | null;
  file_size_bytes: number | null;
}

interface _ApiLessonVideoListResponse {
  lesson_id: string;
  video: _ApiLessonVideo[];
  total: number;
}

interface _ApiGenerateLessonVideoResponse {
  video_id: string;
  status: LessonVideoStatus;
  message: string;
}

export async function getLessonVideoStatus(
  lessonId: string,
): Promise<LessonVideoResponse> {
  try {
    const data = await apiFetch<_ApiLessonVideoListResponse>(
      `/api/v1/video/lesson/${lessonId}`,
    );
    const first = data.video[0];
    if (!first) {
      return { lesson_id: lessonId, status: "pending" };
    }
    return {
      lesson_id: first.lesson_id,
      video_id: first.video_id,
      status: first.status,
      url: first.video_url ?? undefined,
      duration_seconds: first.duration_seconds ?? undefined,
    };
  } catch (err: unknown) {
    // 404 means "no video yet" — same semantics as audio; surface
    // as ``pending`` so the UI can show a generate button.
    const status = (err as { status?: number })?.status;
    if (status === 404) {
      return { lesson_id: lessonId, status: "pending" };
    }
    throw err;
  }
}

export async function generateLessonVideo(
  lessonId: string,
): Promise<_ApiGenerateLessonVideoResponse> {
  return apiFetch<_ApiGenerateLessonVideoResponse>(
    `/api/v1/video/lesson/${lessonId}/generate`,
    { method: "POST" },
  );
}

// ── Platform Settings ─────────────────────────────────────────

export interface PlatformSetting {
  key: string;
  category: string;
  value: unknown;
  default_value: unknown;
  value_type: string;
  label: string;
  description: string;
  validation_rules: { min?: number; max?: number } | null;
  is_sensitive: boolean;
  is_default: boolean;
}

export interface SettingsByCategory {
  category: string;
  settings: PlatformSetting[];
}

export interface PublicConfig {
  settings: Record<string, unknown>;
  branding: Branding;
}

export async function getPublicConfig(): Promise<PublicConfig> {
  const res = await apiFetch<{
    settings: Record<string, unknown>;
    branding?: Branding;
  }>("/api/v1/settings/public");
  return { settings: res.settings, branding: res.branding ?? DEFAULT_BRANDING };
}

export async function getPublicSettings(): Promise<Record<string, unknown>> {
  const { settings } = await getPublicConfig();
  return settings;
}

export async function getAdminSettings(): Promise<SettingsByCategory[]> {
  return apiFetch<SettingsByCategory[]>("/api/v1/admin/settings");
}

export async function updateSetting(
  key: string,
  value: unknown,
): Promise<PlatformSetting> {
  return apiFetch<PlatformSetting>("/api/v1/admin/settings/update", {
    method: "POST",
    body: JSON.stringify({ key, value }),
  });
}

export async function resetSetting(key: string): Promise<PlatformSetting> {
  return apiFetch<PlatformSetting>("/api/v1/admin/settings/reset", {
    method: "POST",
    body: JSON.stringify({ key }),
  });
}

export async function resetSettingCategory(
  category: string,
): Promise<{ category: string; reset_count: number }> {
  return apiFetch(`/api/v1/admin/settings/reset-category/${category}`, {
    method: "POST",
  });
}

// ── Curricula API ─────────────────────────────────────────────

export interface CurriculumPublicResponse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  cover_image_url?: string;
  course_count: number;
  published_at?: string;
}

export interface CurriculumPublicDetailResponse extends CurriculumPublicResponse {
  course_ids: string[];
}

export interface CurriculumAdminResponse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  cover_image_url?: string;
  status: "draft" | "published" | "archived";
  visibility: "public" | "private";
  created_by?: string;
  course_count: number;
  courses?: Array<{
    id: string;
    slug: string;
    title_fr: string;
    title_en: string;
    status: string;
    module_count: number;
    estimated_hours: number;
  }>;
  created_at: string;
  published_at?: string;
}

export interface CurriculumAdminDetailResponse extends CurriculumAdminResponse {
  courses: {
    id: string;
    slug: string;
    title_fr: string;
    title_en: string;
    status: string;
    module_count: number;
    estimated_hours: number;
  }[];
}

export async function getCurricula(): Promise<CurriculumPublicResponse[]> {
  return apiFetch<CurriculumPublicResponse[]>("/api/v1/curricula");
}

export async function getCurriculumBySlug(
  slug: string,
): Promise<CurriculumPublicDetailResponse> {
  return apiFetch<CurriculumPublicDetailResponse>(`/api/v1/curricula/${slug}`);
}

export async function getCoursesByCurriculum(
  curriculumSlug: string,
): Promise<CourseResponse[]> {
  return apiFetch<CourseResponse[]>(
    `/api/v1/courses?curriculum=${encodeURIComponent(curriculumSlug)}`,
  );
}

export async function getAdminCurricula(): Promise<CurriculumAdminResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminResponse[]>(
    "/api/v1/admin/curricula",
  );
}

export async function getAdminCurriculum(
  id: string,
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${id}`,
  );
}

export async function createAdminCurriculum(data: {
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  cover_image_url?: string;
}): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    "/api/v1/admin/curricula",
    {
      method: "POST",
      body: JSON.stringify(data),
    },
  );
}

export async function updateAdminCurriculum(
  id: string,
  data: Partial<{
    title_fr: string;
    title_en: string;
    description_fr: string;
    description_en: string;
    cover_image_url: string;
  }>,
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${id}`,
    {
      method: "PATCH",
      body: JSON.stringify(data),
    },
  );
}

export async function publishAdminCurriculum(
  id: string,
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${id}/publish`,
    {
      method: "POST",
    },
  );
}

export async function archiveAdminCurriculum(
  id: string,
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${id}/archive`,
    {
      method: "POST",
    },
  );
}

export async function deleteAdminCurriculum(id: string): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(`/api/v1/admin/curricula/${id}`, {
    method: "DELETE",
  });
}

export async function assignCurriculumCourses(
  curriculumId: string,
  courseIds: string[],
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${curriculumId}/courses`,
    { method: "PUT", body: JSON.stringify({ course_ids: courseIds }) },
  );
}

export async function setCurriculumVisibility(
  curriculumId: string,
  visibility: "public" | "private",
): Promise<CurriculumAdminDetailResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAdminDetailResponse>(
    `/api/v1/admin/curricula/${curriculumId}/visibility`,
    { method: "POST", body: JSON.stringify({ visibility }) },
  );
}

export interface CurriculumAccessEntry {
  id: string;
  curriculum_id: string;
  user_id?: string;
  group_id?: string;
  user_email?: string;
  group_name?: string;
  granted_at: string;
}

export async function getCurriculumAccess(
  curriculumId: string,
): Promise<CurriculumAccessEntry[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAccessEntry[]>(
    `/api/v1/admin/curricula/${curriculumId}/access`,
  );
}

export async function grantCurriculumAccess(
  curriculumId: string,
  data: { user_id?: string; group_id?: string },
): Promise<CurriculumAccessEntry> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CurriculumAccessEntry>(
    `/api/v1/admin/curricula/${curriculumId}/access`,
    { method: "POST", body: JSON.stringify(data) },
  );
}

export async function revokeCurriculumAccess(
  curriculumId: string,
  accessId: string,
): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(
    `/api/v1/admin/curricula/${curriculumId}/access/${accessId}`,
    { method: "DELETE" },
  );
}

export interface UserGroupResponse {
  id: string;
  name: string;
  description?: string;
  member_count: number;
  created_at: string;
}

export interface UserGroupMember {
  user_id: string;
  email: string;
  name: string;
  joined_at: string;
}

interface GroupDetailResponse extends UserGroupResponse {
  created_by?: string | null;
  members: Array<{
    user_id: string;
    user_email: string | null;
    user_name: string;
    added_at: string;
  }>;
}

export async function getAdminGroups(): Promise<UserGroupResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<UserGroupResponse[]>(
    "/api/v1/admin/groups",
  );
}

export async function createAdminGroup(data: {
  name: string;
  description?: string;
}): Promise<UserGroupResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<UserGroupResponse>(
    "/api/v1/admin/groups",
    {
      method: "POST",
      body: JSON.stringify(data),
    },
  );
}

export async function updateAdminGroup(
  id: string,
  data: { name?: string; description?: string },
): Promise<UserGroupResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<UserGroupResponse>(
    `/api/v1/admin/groups/${id}`,
    {
      method: "PATCH",
      body: JSON.stringify(data),
    },
  );
}

export async function deleteAdminGroup(id: string): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(`/api/v1/admin/groups/${id}`, {
    method: "DELETE",
  });
}

export async function getAdminGroupMembers(
  groupId: string,
): Promise<UserGroupMember[]> {
  const { authClient } = await import("./auth");
  const detail = await authClient.authenticatedFetch<GroupDetailResponse>(
    `/api/v1/admin/groups/${groupId}`,
  );
  return detail.members.map((m) => ({
    user_id: m.user_id,
    email: m.user_email ?? "",
    name: m.user_name,
    joined_at: m.added_at,
  }));
}

export async function addGroupMember(
  groupId: string,
  userId: string,
): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(
    `/api/v1/admin/groups/${groupId}/members`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    },
  );
}

export async function removeGroupMember(
  groupId: string,
  userId: string,
): Promise<void> {
  const { authClient } = await import("./auth");
  await authClient.authenticatedFetch(
    `/api/v1/admin/groups/${groupId}/members/${userId}`,
    {
      method: "DELETE",
    },
  );
}

// ── Expert Activation Codes API ───────────────────────────────

export interface ActivationCodeResponse {
  id: string;
  code: string;
  max_uses: number | null;
  times_used: number;
  is_active: boolean;
  revenue_credits?: number;
  created_at: string;
}

export interface CodeRedemptionResponse {
  id: string;
  learner_name: string;
  learner_email: string;
  redeemed_at: string;
  method: "code" | "qr" | "manual";
  revenue_credits: number;
}

export async function generateActivationCodes(
  courseId: string,
  count: number,
  maxUses?: number,
): Promise<ActivationCodeResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ActivationCodeResponse[]>(
    `/api/v1/expert/courses/${courseId}/codes`,
    {
      method: "POST",
      body: JSON.stringify({ count, max_uses: maxUses ?? null }),
    },
  );
}

export async function getActivationCodes(
  courseId: string,
): Promise<ActivationCodeResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ActivationCodeResponse[]>(
    `/api/v1/expert/courses/${courseId}/codes`,
  );
}

export async function getCodeRedemptions(
  courseId: string,
  codeId: string,
): Promise<CodeRedemptionResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<CodeRedemptionResponse[]>(
    `/api/v1/expert/courses/${courseId}/codes/${codeId}/redemptions`,
  );
}

export async function getCodeQR(
  courseId: string,
  codeId: string,
): Promise<Blob> {
  const { authClient } = await import("./auth");
  const token = await authClient.getValidToken();
  const res = await fetch(
    `${API_BASE}/api/v1/expert/courses/${courseId}/codes/${codeId}/qr`,
    {
      headers: {
        Authorization: `Bearer ${token}`,
      },
    },
  );
  if (!res.ok) throw new ApiError(`API error: ${res.status}`, res.status);
  return res.blob();
}

export async function manualActivate(
  courseId: string,
  codeId: string,
  learnerEmail: string,
): Promise<{ message: string }> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<{ message: string }>(
    `/api/v1/expert/courses/${courseId}/codes/${codeId}/activate`,
    {
      method: "POST",
      body: JSON.stringify({ learner_email: learnerEmail }),
    },
  );
}

// ── Learner Activation Codes API ──────────────────────────────

export interface CurriculumCoursePreview {
  id: string;
  title_fr: string;
  title_en: string;
  cover_image_url?: string;
}

export interface ActivationPreviewResponse {
  valid: boolean;
  type?: "course" | "curriculum";
  // Course fields
  code?: string;
  course_slug?: string;
  course_title_fr?: string;
  course_title_en?: string;
  course_description_fr?: string;
  course_description_en?: string;
  title_fr?: string;
  title_en?: string;
  description_fr?: string;
  description_en?: string;
  cover_image_url?: string;
  expert_name?: string;
  // Curriculum fields
  curriculum_title_fr?: string;
  curriculum_title_en?: string;
  curriculum_description_fr?: string;
  curriculum_description_en?: string;
  organization_name?: string;
  organization_logo_url?: string;
  courses?: CurriculumCoursePreview[];
}

export interface ActivationRedeemResponse {
  status: string;
  course_id?: string;
  course_ids?: string[];
  course_slug?: string;
  enrolled?: boolean;
}

export async function previewActivationCode(
  code: string,
): Promise<ActivationPreviewResponse> {
  return apiFetch<ActivationPreviewResponse>(
    `/api/v1/activate/${encodeURIComponent(code)}/preview`,
  );
}

export async function redeemActivationCode(
  code: string,
  method: "code" | "qr",
): Promise<ActivationRedeemResponse> {
  return apiFetch<ActivationRedeemResponse>(
    `/api/v1/activate/${encodeURIComponent(code)}/redeem`,
    { method: "POST", body: JSON.stringify({ method }) },
  );
}

// ── Organization API ──────────────────────────────────────────

export interface OrgResponse {
  id: string;
  name: string;
  slug: string;
  description?: string;
  logo_url?: string;
  contact_email?: string;
  is_active: boolean;
  created_at: string;
}

export interface OrgWithRole {
  organization: OrgResponse;
  role: string;
  joined_at: string;
}

export interface OrgMember {
  user_id: string;
  name: string;
  email?: string;
  role: string;
  joined_at: string;
}

export interface OrgCurriculumResponse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  cover_image_url?: string;
  status: string;
  organization_id?: string;
  course_count: number;
}

export interface OrgCodeResponse {
  id: string;
  code: string;
  course_id?: string;
  curriculum_id?: string;
  max_uses?: number;
  times_used: number;
  is_active: boolean;
  created_at: string;
}

export interface OrgSummary {
  total_codes: number;
  active_codes: number;
  total_redemptions: number;
  unique_learners: number;
  avg_completion_pct: number;
}

export interface LearnerProgress {
  user_id: string;
  name: string;
  email?: string;
  activated_at?: string;
  courses_enrolled: number;
  avg_completion_pct: number;
}

// Organization CRUD
export async function fetchMyOrganizations(): Promise<OrgWithRole[]> {
  return apiFetch<OrgWithRole[]>("/api/v1/organizations/me");
}

export async function fetchOrganization(orgId: string): Promise<OrgResponse> {
  return apiFetch<OrgResponse>(`/api/v1/organizations/${orgId}`);
}

export async function createOrganization(data: {
  name: string;
  slug?: string;
  description?: string;
  contact_email?: string;
}): Promise<OrgResponse> {
  return apiFetch<OrgResponse>("/api/v1/organizations", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// Organization Members
export async function fetchOrgMembers(orgId: string): Promise<OrgMember[]> {
  return apiFetch<OrgMember[]>(`/api/v1/organizations/${orgId}/members`);
}

export async function addOrgMember(
  orgId: string,
  email: string,
  role: string,
): Promise<OrgMember> {
  return apiFetch<OrgMember>(`/api/v1/organizations/${orgId}/members`, {
    method: "POST",
    body: JSON.stringify({ email, role }),
  });
}

export async function removeOrgMember(
  orgId: string,
  userId: string,
): Promise<void> {
  return apiFetch<void>(`/api/v1/organizations/${orgId}/members/${userId}`, {
    method: "DELETE",
  });
}

// Organization Credits
export async function fetchOrgCredits(
  orgId: string,
): Promise<{ balance: number }> {
  return apiFetch<{ balance: number }>(
    `/api/v1/organizations/${orgId}/credits`,
  );
}

// Organization Curricula
export async function fetchOrgCurricula(
  orgId: string,
): Promise<OrgCurriculumResponse[]> {
  return apiFetch<OrgCurriculumResponse[]>(
    `/api/v1/organizations/${orgId}/curricula`,
  );
}

export async function createOrgCurriculum(
  orgId: string,
  data: {
    title_fr: string;
    title_en: string;
    slug: string;
    description_fr?: string;
    description_en?: string;
  },
): Promise<OrgCurriculumResponse> {
  return apiFetch<OrgCurriculumResponse>(
    `/api/v1/organizations/${orgId}/curricula`,
    {
      method: "POST",
      body: JSON.stringify(data),
    },
  );
}

export async function fetchOrgCourses(orgId: string): Promise<
  {
    id: string;
    slug: string;
    title_fr: string;
    title_en: string;
    status: string;
    creation_mode: string;
    creation_step: string;
    created_at: string;
    cover_image_url?: string;
  }[]
> {
  return apiFetch(`/api/v1/organizations/${orgId}/courses`);
}

export async function setOrgCurriculumCourses(
  orgId: string,
  curriculumId: string,
  courseIds: string[],
): Promise<OrgCurriculumResponse> {
  return apiFetch<OrgCurriculumResponse>(
    `/api/v1/organizations/${orgId}/curricula/${curriculumId}/courses`,
    { method: "PUT", body: JSON.stringify({ course_ids: courseIds }) },
  );
}

// Organization Codes
export async function fetchOrgCodes(orgId: string): Promise<OrgCodeResponse[]> {
  return apiFetch<OrgCodeResponse[]>(`/api/v1/organizations/${orgId}/codes`);
}

export async function generateOrgCodes(
  orgId: string,
  data: {
    curriculum_id?: string;
    course_id?: string;
    count: number;
    max_uses?: number;
  },
): Promise<OrgCodeResponse[]> {
  return apiFetch<OrgCodeResponse[]>(`/api/v1/organizations/${orgId}/codes`, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function revokeOrgCode(
  orgId: string,
  codeId: string,
): Promise<void> {
  return apiFetch<void>(
    `/api/v1/organizations/${orgId}/codes/${codeId}/revoke`,
    {
      method: "POST",
    },
  );
}

// Organization Reports
export async function fetchOrgSummary(orgId: string): Promise<OrgSummary> {
  return apiFetch<OrgSummary>(`/api/v1/organizations/${orgId}/reports/summary`);
}

export async function fetchOrgLearners(
  orgId: string,
  params?: {
    curriculum_id?: string;
    course_id?: string;
    limit?: number;
    offset?: number;
  },
): Promise<LearnerProgress[]> {
  const searchParams = new URLSearchParams();
  if (params?.curriculum_id)
    searchParams.set("curriculum_id", params.curriculum_id);
  if (params?.course_id) searchParams.set("course_id", params.course_id);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));
  const qs = searchParams.toString();
  return apiFetch<LearnerProgress[]>(
    `/api/v1/organizations/${orgId}/reports/learners${qs ? `?${qs}` : ""}`,
  );
}

export async function exportOrgCsv(orgId: string): Promise<string> {
  const res = await fetch(
    `${API_BASE}/api/v1/organizations/${orgId}/reports/export`,
    {
      headers: {
        Authorization: `Bearer ${localStorage.getItem("access_token")}`,
      },
    },
  );
  return res.text();
}

// ── Certificate Types ─────────────────────────────────────────────

export interface CertificateTemplateResponse {
  id: string;
  course_id: string;
  title_fr: string;
  title_en: string;
  organization_name: string | null;
  signatory_name: string | null;
  signatory_title: string | null;
  logo_url: string | null;
  additional_text_fr: string | null;
  additional_text_en: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CertificateListItem {
  id: string;
  course_id: string;
  course_title_fr: string;
  course_title_en: string;
  verification_code: string;
  average_score: number;
  completed_at: string;
  issued_at: string;
  status: string;
}

export interface CertificateVerifyResponse {
  valid: boolean;
  learner_name: string | null;
  course_title_fr: string | null;
  course_title_en: string | null;
  completion_date: string | null;
  average_score: number | null;
  organization_name: string | null;
  signatory_name: string | null;
  status: string | null;
}

// ── Certificate API Functions ─────────────────────────────────────

export async function getCertificateTemplate(
  courseId: string,
): Promise<CertificateTemplateResponse> {
  return apiFetch<CertificateTemplateResponse>(
    `/api/v1/expert/courses/${courseId}/certificate-template`,
  );
}

export async function upsertCertificateTemplate(
  courseId: string,
  data: Partial<CertificateTemplateResponse>,
): Promise<CertificateTemplateResponse> {
  return apiFetch<CertificateTemplateResponse>(
    `/api/v1/expert/courses/${courseId}/certificate-template`,
    {
      method: "POST",
      body: JSON.stringify(data),
    },
  );
}

export async function getMyCertificates(): Promise<CertificateListItem[]> {
  return apiFetch<CertificateListItem[]>("/api/v1/certificates");
}

export async function downloadCertificatePdf(
  certificateId: string,
): Promise<Blob> {
  const headers: Record<string, string> = {};
  if (typeof window !== "undefined") {
    try {
      const { authClient } = await import("./auth");
      const token = await authClient.getValidToken();
      headers["Authorization"] = `Bearer ${token}`;
    } catch {
      // proceed without auth
    }
  }
  const res = await fetch(
    `${API_BASE}/api/v1/certificates/${certificateId}/download`,
    { headers },
  );
  if (!res.ok) throw new ApiError("Download failed", res.status);
  return res.blob();
}

export async function verifyCertificate(
  code: string,
): Promise<CertificateVerifyResponse> {
  return apiFetch<CertificateVerifyResponse>(`/api/v1/verify/${code}`);
}

// Question Bank API
export interface QBankQuestion {
  id: string;
  image_url: string | null;
  question_text: string;
  options: string[];
  category: string | null;
  difficulty: string;
  /**
   * Populated only when the test is in training mode with show_feedback=true.
   * Lets the player draw "Correct"/"Incorrect" without a per-click round-trip.
   * Undefined in exam mode so devtools users can't peek the answer key. (#1632)
   */
  correct_answer_indices?: number[] | null;
}

export interface QBankTestStartResponse {
  test_id: string;
  title: string;
  mode: string;
  time_per_question_sec: number;
  show_feedback: boolean;
  questions: QBankQuestion[];
  total_questions: number;
  /**
   * Pre-fetched audio URLs: {question_id: {language: url}}. Only
   * (question, language) pairs whose TTS clip is ready are populated.
   * Missing entries mean the client should fall back to polling
   * /api/v1/qbank/questions/{id}/audio (#1674).
   */
  audio?: Record<string, Record<string, string>>;
}

export interface QBankTestAttemptResponse {
  id: string;
  test_id: string;
  score: number;
  total_questions: number;
  correct_answers: number;
  time_taken_sec: number;
  passed: boolean;
  category_breakdown: Record<string, { correct: number; total: number }> | null;
  attempted_at: string;
  attempt_number: number;
}

export interface QBankReviewQuestion {
  id: string;
  image_url: string | null;
  question_text: string;
  options: string[];
  correct_answer_indices: number[];
  explanation: string | null;
  category: string | null;
  user_selected: number[] | null;
  is_correct: boolean | null;
}

export interface QBankReviewResponse {
  test_id: string;
  attempt_id: string;
  score: number;
  passed: boolean;
  questions: QBankReviewQuestion[];
}

export async function startQBankTest(
  testId: string,
): Promise<QBankTestStartResponse> {
  return apiFetch<QBankTestStartResponse>(
    `/api/v1/qbank/tests/${testId}/start`,
  );
}

export async function submitQBankTest(
  testId: string,
  answers: Record<string, { selected: number[]; time_sec: number }>,
): Promise<QBankTestAttemptResponse> {
  return apiFetch<QBankTestAttemptResponse>(
    `/api/v1/qbank/tests/${testId}/submit`,
    {
      method: "POST",
      body: JSON.stringify({ answers }),
    },
  );
}

export async function getQBankTestHistory(
  testId: string,
): Promise<QBankTestAttemptResponse[]> {
  return apiFetch<QBankTestAttemptResponse[]>(
    `/api/v1/qbank/tests/${testId}/history`,
  );
}

export async function getQBankTestReview(
  testId: string,
  attemptId: string,
): Promise<QBankReviewResponse> {
  return apiFetch<QBankReviewResponse>(
    `/api/v1/qbank/tests/${testId}/review/${attemptId}`,
  );
}

// Question audio — backend streams OGG/Opus from MinIO via a proxy (#1658).
// The status poll returns `audio_url` only when `status === "ready"`.
export type QBankAudioLanguage = "fr" | "mos" | "dyu" | "bam" | "ful";

export type QBankAudioReadiness = "pending" | "generating" | "ready" | "failed";

export type QBankAudioSource = "tts" | "manual";

export interface QBankQuestionAudioStatus {
  question_id: string;
  language: QBankAudioLanguage;
  status: QBankAudioReadiness;
  audio_url: string | null;
  duration_seconds: number | null;
  /**
   * ``manual`` when the editor uploaded/recorded the clip; ``tts`` for
   * everything auto-generated. Defaults to ``tts`` for backend responses
   * that predate #1747.
   */
  source?: QBankAudioSource;
}

export async function getQBankQuestionAudio(
  questionId: string,
  language: QBankAudioLanguage,
): Promise<QBankQuestionAudioStatus> {
  return apiFetch<QBankQuestionAudioStatus>(
    `/api/v1/qbank/questions/${questionId}/audio?lang=${language}`,
  );
}

/**
 * Upload a manual audio clip (recorded or chosen from disk) to replace
 * the TTS output for one (question, language) pair (#1747). Bypasses
 * ``apiFetch`` because that helper always sets ``Content-Type:
 * application/json``, which would clobber the multipart boundary the
 * browser needs to set.
 */
export async function uploadQBankQuestionAudio(
  questionId: string,
  language: QBankAudioLanguage,
  file: Blob,
  filename?: string,
): Promise<QBankQuestionAudioStatus> {
  const form = new FormData();
  form.append("file", file, filename ?? `audio-${language}`);
  const headers: Record<string, string> = {};
  if (typeof window !== "undefined") {
    try {
      const { authClient } = await import("./auth");
      const token = await authClient.getValidToken();
      headers["Authorization"] = `Bearer ${token}`;
    } catch {
      // unauthenticated — backend will 401
    }
  }
  const res = await fetch(
    `${API_BASE}/api/v1/qbank/questions/${questionId}/audio?language=${language}`,
    { method: "POST", headers, body: form },
  );
  if (!res.ok) {
    let message = `API error: ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (body?.detail?.message) message = body.detail.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(message, res.status);
  }
  return res.json();
}

/**
 * Remove the (question, language) audio row — used to clear a manual
 * clip so the next TTS batch can repopulate the slot (#1747).
 */
export async function deleteQBankQuestionAudio(
  questionId: string,
  language: QBankAudioLanguage,
): Promise<void> {
  await apiFetch<void>(
    `/api/v1/qbank/questions/${questionId}/audio?language=${language}`,
    { method: "DELETE" },
  );
}

// ---------------------------------------------------------------------------
// QBank management (org admin) — #1504
// ---------------------------------------------------------------------------

export type QBankType =
  | "driving"
  | "exam_prep"
  | "psychotechnic"
  | "general_culture";
export type QBankStatus = "draft" | "published" | "archived";
export type QBankDifficulty = "easy" | "medium" | "hard";
export type QBankTestMode = "exam" | "training" | "review";
export type QBankVisibility = "public" | "org_restricted";

export interface QBankBank {
  id: string;
  organization_id: string | null;
  /** Populated by the cross-org ``/banks/accessible`` endpoint (#1692). */
  organization_name?: string | null;
  organization_slug?: string | null;
  visibility: QBankVisibility;
  title: string;
  description: string | null;
  bank_type: QBankType;
  language: string;
  time_per_question_sec: number;
  passing_score: number;
  status: QBankStatus;
  question_count: number;
  test_count: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface QBankBankCreate {
  organization_id?: string | null;
  visibility?: QBankVisibility;
  title: string;
  description?: string | null;
  bank_type: QBankType;
  language?: string;
  time_per_question_sec?: number;
  passing_score?: number;
}

export interface QBankBankUpdate {
  title?: string;
  description?: string | null;
  language?: string;
  time_per_question_sec?: number;
  passing_score?: number;
  status?: QBankStatus;
  visibility?: QBankVisibility;
}

export interface QBankQuestionFull {
  id: string;
  question_bank_id: string;
  order_index: number;
  image_url: string | null;
  question_text: string;
  options: string[];
  correct_answer_indices: number[];
  explanation: string | null;
  source_page: number | null;
  source_pdf_name: string | null;
  category: string | null;
  difficulty: QBankDifficulty;
  created_at: string;
}

export interface QBankQuestionList {
  questions: QBankQuestionFull[];
  total: number;
  page: number;
  per_page: number;
}

export interface QBankQuestionUpdate {
  question_text?: string;
  options?: string[];
  correct_answer_indices?: number[];
  explanation?: string | null;
  category?: string | null;
  difficulty?: QBankDifficulty;
}

export interface QBankTestConfig {
  id: string;
  question_bank_id: string;
  title: string;
  mode: QBankTestMode;
  question_count: number | null;
  shuffle_questions: boolean;
  time_per_question_sec: number | null;
  show_feedback: boolean;
  filter_categories: string[] | null;
  filter_failed_only: boolean;
  created_by: string;
  created_at: string;
}

export interface QBankTestCreate {
  question_bank_id: string;
  title: string;
  mode: QBankTestMode;
  question_count?: number | null;
  shuffle_questions?: boolean;
  time_per_question_sec?: number | null;
  show_feedback?: boolean;
  filter_categories?: string[] | null;
  filter_failed_only?: boolean;
}

export interface QBankProcessingStatus {
  task_id: string;
  bank_id: string;
  status: string;
  result?: { bank_id: string; questions_created: number; errors: unknown[] };
  error?: string;
}

export async function listQBankBanks(orgId: string): Promise<QBankBank[]> {
  return apiFetch<QBankBank[]>(`/api/v1/qbank/banks?org_id=${orgId}`);
}

/** Every qbank the current user can reach across all their orgs (#1692). */
export async function listAccessibleQBanks(options?: {
  includeDrafts?: boolean;
}): Promise<QBankBank[]> {
  const qs = options?.includeDrafts ? "?include_drafts=true" : "";
  return apiFetch<QBankBank[]>(`/api/v1/qbank/banks/accessible${qs}`);
}

/** A test the learner can take, with enough bank context to render without
 * drilling into the bank. Powers the /qbank/tests discovery page (#1732). */
export interface AccessibleQBankTest {
  id: string;
  question_bank_id: string;
  title: string;
  mode: "exam" | "training" | "review" | string;
  question_count: number | null;
  time_per_question_sec: number | null;
  show_feedback: boolean;
  created_at: string;
  bank_title: string | null;
  bank_language: string | null;
  bank_org_name: string | null;
  bank_org_slug: string | null;
}

/** Flat list of every test the learner can take across accessible banks
 * (#1732). Cross-org, published-only, grouped client-side by bank. */
export async function listAccessibleTests(): Promise<AccessibleQBankTest[]> {
  return apiFetch<AccessibleQBankTest[]>(`/api/v1/qbank/tests/accessible`);
}

export async function createQBankBank(
  body: QBankBankCreate,
): Promise<QBankBank> {
  return apiFetch<QBankBank>(`/api/v1/qbank/banks`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getQBankBank(bankId: string): Promise<QBankBank> {
  return apiFetch<QBankBank>(`/api/v1/qbank/banks/${bankId}`);
}

export async function updateQBankBank(
  bankId: string,
  body: QBankBankUpdate,
): Promise<QBankBank> {
  return apiFetch<QBankBank>(`/api/v1/qbank/banks/${bankId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteQBankBank(bankId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/qbank/banks/${bankId}`, { method: "DELETE" });
}

export async function listQBankQuestions(
  bankId: string,
  page = 1,
  perPage = 50,
): Promise<QBankQuestionList> {
  return apiFetch<QBankQuestionList>(
    `/api/v1/qbank/banks/${bankId}/questions?page=${page}&per_page=${perPage}`,
  );
}

export async function updateQBankQuestion(
  questionId: string,
  body: QBankQuestionUpdate,
): Promise<QBankQuestionFull> {
  return apiFetch<QBankQuestionFull>(`/api/v1/qbank/questions/${questionId}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function deleteQBankQuestion(questionId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/qbank/questions/${questionId}`, {
    method: "DELETE",
  });
}

export async function listQBankTests(
  bankId: string,
): Promise<QBankTestConfig[]> {
  return apiFetch<QBankTestConfig[]>(`/api/v1/qbank/tests?bank_id=${bankId}`);
}

export async function createQBankTest(
  body: QBankTestCreate,
): Promise<QBankTestConfig> {
  return apiFetch<QBankTestConfig>(`/api/v1/qbank/tests`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function uploadQBankPdf(
  bankId: string,
  file: File,
): Promise<{
  task_id: string;
  bank_id: string;
  filename: string;
  status: string;
}> {
  const formData = new FormData();
  formData.append("file", file);
  const headers: Record<string, string> = {};
  if (typeof window !== "undefined") {
    try {
      const { authClient } = await import("./auth");
      const token = await authClient.getValidToken();
      headers["Authorization"] = `Bearer ${token}`;
    } catch {
      // no auth header if no token
    }
  }
  const res = await fetch(
    `${API_BASE}/api/v1/qbank/banks/${bankId}/upload-pdf`,
    {
      method: "POST",
      headers,
      body: formData,
    },
  );
  if (!res.ok) {
    let message = `API error: ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (body?.detail?.message) message = body.detail.message;
    } catch {
      /* ignore */
    }
    throw new ApiError(message, res.status);
  }
  return res.json();
}

export async function getQBankProcessingStatus(
  bankId: string,
  taskId: string,
): Promise<QBankProcessingStatus> {
  return apiFetch<QBankProcessingStatus>(
    `/api/v1/qbank/banks/${bankId}/processing-status?task_id=${taskId}`,
  );
}
