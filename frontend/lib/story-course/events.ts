/**
 * Anonymised story events (#2711): a bet, a first answer, a finished chapter.
 *
 * Story progress lives in the browser, so without these nobody can tell
 * whether betting before the explanation helps. They go to
 * `POST /api/v1/analytics/story-events`, which keeps no user, no session and no
 * free text. The learner's analytics opt-out is honoured (nothing is sent or
 * queued). Offline, or when the POST fails on a transient error, the event is
 * queued with the other offline actions and replayed by the sync manager.
 */

import { apiFetch } from "@/lib/api";
import { addOfflineAction, requestOfflineReplay } from "@/lib/offline/db";

export type StoryEvent =
  | {
      event: "story_prediction";
      story: string;
      chapter?: string;
      question: string;
      lang?: "fr" | "en";
      matched: boolean;
    }
  | {
      event: "story_first_try";
      story: string;
      chapter?: string;
      question: string;
      lang?: "fr" | "en";
      correct: boolean;
      attempts: 1 | 2;
    }
  | {
      event: "story_chapter_complete";
      story: string;
      chapter?: string;
      lang?: "fr" | "en";
      stars: 0 | 1 | 2 | 3;
    };

/** Ids the server accepts: no space, no accent, no free text. */
const ID = /^[A-Za-z0-9._:-]{1,100}$/;

/** The opt-out the profile page sets (the same key `lib/analytics.ts` reads). */
export function analyticsOptedOut(): boolean {
  try {
    return typeof window !== "undefined" && window.localStorage.getItem("analytics_opt_out") === "1";
  } catch {
    return false;
  }
}

/** The event as the server will take it, or null when it carries something it would refuse. */
export function cleanStoryEvent(event: StoryEvent): StoryEvent | null {
  const ids = [event.story, event.chapter, "question" in event ? event.question : undefined];
  if (ids.some((id) => id !== undefined && !ID.test(id))) return null;
  return event;
}

/** Send one event now, or queue it. Never throws: measuring must not break a story. */
export async function reportStoryEvent(event: StoryEvent): Promise<"sent" | "queued" | "skipped"> {
  const clean = cleanStoryEvent(event);
  if (!clean || analyticsOptedOut()) return "skipped";
  const queue = async (): Promise<"queued" | "skipped"> => {
    try {
      await addOfflineAction({ actionType: "story_events", payload: { events: [clean] } });
      requestOfflineReplay();
      return "queued";
    } catch {
      return "skipped";
    }
  };
  if (typeof navigator !== "undefined" && navigator.onLine === false) return queue();
  try {
    await postStoryEvents([clean]);
    return "sent";
  } catch (error) {
    const status = (error as { status?: number } | null)?.status;
    // A refusal (4xx) will not change on a retry: drop it. The rest is the network.
    if (typeof status === "number" && status >= 400 && status < 500) return "skipped";
    return queue();
  }
}

/** The POST the sync manager replays for a queued batch. */
export async function postStoryEvents(events: StoryEvent[]): Promise<void> {
  await apiFetch("/api/v1/analytics/story-events", {
    method: "POST",
    body: JSON.stringify({ events }),
  });
}
