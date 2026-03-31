const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function apiFetch<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// Alias for backward compatibility and common usage
export const fetchApi = apiFetch;

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
  // Get user's timezone offset for accurate streak calculations
  const timezoneOffset = -new Date().getTimezoneOffset() / 60; // Convert to hours
  const offsetString = timezoneOffset >= 0 ? 
    `+${timezoneOffset.toString().padStart(2, '0')}:00` : 
    `${timezoneOffset.toString().padStart(3, '0')}:00`;

  return apiFetch<DashboardStats>("/api/v1/dashboard/stats", {
    headers: {
      "X-Timezone-Offset": offsetString,
    },
  });
}
<<<<<<< HEAD
=======

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
>>>>>>> 3d0e726 (feat: implement summative assessment with 20 questions and 80% pass gate)
