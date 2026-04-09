import posthog from "posthog-js";
import { API_BASE } from "./api";

type AnalyticsEvent =
  | {
      event: "quiz_started";
      properties: { module_id: string; level: number; language: string };
    }
  | {
      event: "quiz_completed";
      properties: {
        module_id: string;
        score: number;
        passed: boolean;
        duration_seconds: number;
      };
    }
  | {
      event: "lesson_viewed";
      properties: { module_id: string; unit_id: string; language: string };
    }
  | {
      event: "flashcard_reviewed";
      properties: { module_id: string; rating: number };
    }
  | {
      event: "tutor_message_sent";
      properties: { module_id: string; language: string };
    }
  | {
      event: "language_switched";
      properties: { from: string; to: string };
    }
  | {
      event: "module_unlocked";
      properties: { module_id: string; level: number };
    };

function isOptedOut(): boolean {
  return typeof window !== "undefined" && localStorage.getItem("analytics_opt_out") === "1";
}

export function track<E extends AnalyticsEvent>(
  event: E["event"],
  properties: E["properties"]
) {
  if (typeof window === "undefined" || isOptedOut()) return;

  // PostHog (client-side analytics)
  if (process.env.NEXT_PUBLIC_POSTHOG_KEY) {
    posthog.capture(event, properties);
  }

  // Backend DB (admin dashboard analytics)
  const token = localStorage.getItem("access_token");
  fetch(`${API_BASE}/api/v1/analytics/events`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ event_name: event, properties }),
  }).catch((err) => {
    console.error("[analytics] Failed to send event to backend:", err);
  });
}

/**
 * Identify user with pseudonymized ID only (no email/name).
 */
export function identifyUser(
  userId: string,
  properties?: {
    country?: string;
    level?: number;
    preferred_language?: string;
  }
) {
  if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_POSTHOG_KEY) {
    posthog.identify(userId, properties);
  }
}

export function resetAnalytics() {
  if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_POSTHOG_KEY) {
    posthog.reset();
  }
}
