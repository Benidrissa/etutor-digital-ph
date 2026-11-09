/**
 * Loading a module story, with the offline copy as a fallback (contract C-5).
 *
 * Network first: the server decides whether the cached story is still fresh,
 * so a learner online always gets the current one (or the 202 while it is
 * rewritten). The IndexedDB copy is used when the device is offline or the
 * request never got through, which is what a downloaded module is for on 2G.
 *
 * The story is stored per module and language under the module's pseudo-unit
 * key, the one module flashcards already use, so it never collides with a
 * unit's own content and goes when the module download is removed.
 */

import { apiFetch } from "@/lib/api";
import { getOfflineContent, upsertOfflineContent } from "@/lib/offline/db";
import { OfflineContentNotAvailable } from "@/lib/offline/content-loader";

import {
  isStoryDocument,
  isStoryGenerating,
  moduleStoryPath,
  type StoryGenerating,
} from "./api";
import type { StoryCourse } from "./types";

/** The IndexedDB unit key a module story is stored under (shared with the downloader). */
export function moduleStoryUnitKey(moduleId: string): string {
  return `__module_${moduleId}__`;
}

/** True when the request never reached the server (as opposed to a 4xx/5xx answer). */
function isNetworkFailure(err: unknown): boolean {
  if (err && typeof err === "object" && "status" in err) return false;
  if (err instanceof TypeError) return true;
  return (
    err instanceof Error &&
    /network|failed to fetch|load failed/i.test(err.message)
  );
}

async function readCachedStory(
  moduleId: string,
  locale: "fr" | "en",
): Promise<StoryCourse | null> {
  try {
    const cached = await getOfflineContent(
      moduleId,
      moduleStoryUnitKey(moduleId),
      "story",
      locale,
    );
    return cached && isStoryDocument(cached.content) ? cached.content : null;
  } catch {
    // IndexedDB can be missing or blocked (private mode): no offline copy.
    return null;
  }
}

/**
 * The module story in `locale`: the document, or the 202 envelope while it
 * is being written. Throws {@link OfflineContentNotAvailable} when offline
 * with no downloaded copy, and the API's error (403/404/409) otherwise.
 */
export async function loadModuleStory(
  moduleId: string,
  locale: "fr" | "en",
): Promise<StoryCourse | StoryGenerating> {
  const unitKey = moduleStoryUnitKey(moduleId);
  const online = typeof navigator === "undefined" ? true : navigator.onLine !== false;

  if (!online) {
    const cached = await readCachedStory(moduleId, locale);
    if (cached) return cached;
    throw new OfflineContentNotAvailable(unitKey, "story");
  }

  let data: unknown;
  try {
    data = await apiFetch<unknown>(moduleStoryPath(moduleId, locale));
  } catch (err) {
    // A 403/404/409 is the server's answer and must not be papered over by
    // an old copy: only a request that never got through falls back.
    if (!isNetworkFailure(err)) throw err;
    const cached = await readCachedStory(moduleId, locale);
    if (cached) return cached;
    throw new OfflineContentNotAvailable(unitKey, "story");
  }

  if (isStoryGenerating(data)) return data;
  if (!isStoryDocument(data)) throw new Error("Unexpected module story response");

  // Only the bare, name-free document is stored (fire-and-forget).
  upsertOfflineContent({
    unitId: unitKey,
    moduleId,
    contentType: "story",
    locale,
    content: data,
    cachedAt: Date.now(),
  }).catch(() => {
    /* An IndexedDB write failure is not fatal: the story still plays. */
  });
  return data;
}
