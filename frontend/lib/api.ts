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
