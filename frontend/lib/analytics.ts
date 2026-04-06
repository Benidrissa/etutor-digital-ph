import posthog from "posthog-js";

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
  if (typeof window !== "undefined" && process.env.NEXT_PUBLIC_POSTHOG_KEY && !isOptedOut()) {
    posthog.capture(event, properties);
  }
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
