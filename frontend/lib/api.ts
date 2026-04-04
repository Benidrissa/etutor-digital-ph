export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Course Catalog API Types
export interface CourseResponse {
  id: string;
  slug: string;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  domain: string;
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

export async function getCourses(): Promise<CourseResponse[]> {
  return apiFetch<CourseResponse[]>("/api/v1/courses");
}

export async function enrollInCourse(courseId: string): Promise<EnrollmentResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<EnrollmentResponse>(
    `/api/v1/courses/${courseId}/enroll`,
    { method: "POST" }
  );
}

// Progress API Types
export interface ModuleProgressResponse {
  module_id: string;
  user_id: string;
  module_number: number | null;
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
export async function getModuleProgress(moduleId: string): Promise<ModuleProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleProgressResponse>(
    `/api/v1/progress/modules/${moduleId}`
  );
}

export async function getAllModuleProgress(): Promise<ModuleProgressResponse[]> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleProgressResponse[]>("/api/v1/progress/modules");
}

export async function getModuleDetailWithProgress(
  moduleId: string
): Promise<ModuleDetailWithProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleDetailWithProgressResponse>(
    `/api/v1/progress/modules/${moduleId}/detail`
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
  units: PublicUnitDetail[];
}

export async function getModuleUnits(moduleId: string): Promise<ModuleUnitsResponse> {
  return apiFetch<ModuleUnitsResponse>(`/api/v1/content/modules/${moduleId}/units`);
}

export async function trackLessonAccess(
  request: LessonAccessRequest
): Promise<ModuleProgressResponse> {
  const { authClient } = await import("./auth");
  return authClient.authenticatedFetch<ModuleProgressResponse>("/api/v1/progress/lesson-access", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
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
    try {
      const body = await res.json();
      if (body?.detail?.message) message = body.detail.message;
      else if (typeof body?.detail === 'string') message = body.detail;
    } catch {
      // ignore parse errors — keep the status-code message
    }
    throw new Error(message);
  }
  return res.json();
}

// Alias for backward compatibility and common usage
export const fetchApi = apiFetch;

// Lesson Image API Types
export type LessonImageStatus = 'pending' | 'generating' | 'ready' | 'failed';

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

export async function getLessonImageStatus(lessonId: string): Promise<LessonImageResponse> {
  const data = await apiFetch<_ApiLessonImagesListResponse>(`/api/v1/images/lesson/${lessonId}`);
  const first = data.images[0];
  if (!first) {
    return { lesson_id: lessonId, status: 'pending' };
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
  const { authClient } = await import('./auth');
  
  // Get user's timezone offset for accurate streak calculations
  const timezoneOffset = -new Date().getTimezoneOffset() / 60; // Convert to hours
  const offsetString = timezoneOffset >= 0 ? 
    `+${timezoneOffset.toString().padStart(2, '0')}:00` : 
    `${timezoneOffset.toString().padStart(3, '0')}:00`;

  return authClient.authenticatedFetch<DashboardStats>("/api/v1/dashboard/stats", {
    headers: {
      "X-Timezone-Offset": offsetString,
    },
  });
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
  const { authClient } = await import('./auth');
  return authClient.authenticatedFetch<UpcomingReviewsResponse>("/api/v1/flashcards/upcoming");
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
  const { authClient } = await import('./auth');
  const level = params.level ?? 1;
  return authClient.authenticatedFetch<FlashcardSetResponse>(
    `/api/v1/flashcards/modules/${params.moduleId}?language=${params.language}&level=${level}`
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
  request: QuizAttemptRequest
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
  unitId: string
): Promise<UnitQuizValidationStatus> {
  return apiFetch<UnitQuizValidationStatus>(
    `/api/v1/quiz/attempts/status?module_id=${encodeURIComponent(moduleId)}&unit_id=${encodeURIComponent(unitId)}`
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
  moduleId: string
): Promise<SummativeAssessmentAttemptCheck> {
  return apiFetch<SummativeAssessmentAttemptCheck>(
    `/api/v1/quiz/summative/${moduleId}/can-attempt`
  );
}

export async function submitSummativeAssessmentAttempt(
  request: QuizAttemptRequest
): Promise<SummativeAssessmentResponse> {
  return apiFetch<SummativeAssessmentResponse>("/api/v1/quiz/summative/attempt", {
    method: "POST",
    body: JSON.stringify(request),
  });
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

export async function getPublicSettings(): Promise<Record<string, unknown>> {
  const res = await apiFetch<{ settings: Record<string, unknown> }>("/api/v1/settings/public");
  return res.settings;
}

export async function getAdminSettings(): Promise<SettingsByCategory[]> {
  return apiFetch<SettingsByCategory[]>("/api/v1/admin/settings");
}

export async function updateSetting(key: string, value: unknown): Promise<PlatformSetting> {
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
  category: string
): Promise<{ category: string; reset_count: number }> {
  return apiFetch(`/api/v1/admin/settings/reset-category/${category}`, { method: "POST" });
}
