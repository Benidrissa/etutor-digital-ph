import {
  upsertOfflineModule,
  upsertOfflineContent,
  getOfflineModule,
  getAllOfflineModules,
  deleteOfflineModule,
  type ContentType,
} from "./db";
import { prewarmPage } from "./prewarm";
import { apiFetch } from "@/lib/api";
import type { ModuleUnitsResponse } from "@/lib/api";
import {
  isStoryDocument,
  isStoryGenerating,
  moduleStoryPath,
  storyErrorCode,
} from "@/lib/story-course/api";

const MAX_OFFLINE_MODULES = 3;
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

// Average bytes per content type (for size estimation).
const SIZE_ESTIMATE_PER_UNIT = 50_000; // ~50KB per unit (lesson + quiz + case study)
const SIZE_ESTIMATE_FLASHCARDS = 30_000; // ~30KB for module flashcards
// One module story when it is already written: a story-course/1 document with
// a chapter per unit, 100-200KB of JSON (25-40KB gzipped on the wire). An
// upper bound: a story nobody has opened yet is skipped.
const SIZE_ESTIMATE_MODULE_STORY = 150_000;

export type DownloadPhase = "fetching_structure" | "downloading_content" | "complete" | "error" | "cancelled";

export interface DownloadProgress {
  phase: DownloadPhase;
  totalUnits: number;
  downloadedUnits: number;
  currentUnit?: string;
  currentContentType?: ContentType;
  error?: string;
}

export type DownloadProgressCallback = (progress: DownloadProgress) => void;

interface ContentStatusResponse {
  status: string;
  content_id?: string;
  error?: string;
}

/**
 * Estimate download size in bytes for a module based on unit count.
 */
export function estimateModuleSize(unitCount: number): number {
  return unitCount * SIZE_ESTIMATE_PER_UNIT + SIZE_ESTIMATE_FLASHCARDS + SIZE_ESTIMATE_MODULE_STORY;
}

/**
 * Format bytes as human-readable string.
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Active downloads tracked for cancellation
const activeAbortControllers = new Map<string, AbortController>();

/**
 * Check whether the current connection is WiFi.
 * Returns true if WiFi, false if cellular, undefined if API not available.
 */
function isWifiConnection(): boolean | undefined {
  const conn = (navigator as unknown as { connection?: { type?: string } }).connection;
  if (!conn?.type) return undefined;
  return conn.type === "wifi";
}

/**
 * Get count of currently downloaded (or downloading) modules.
 */
export async function getDownloadedModuleCount(): Promise<number> {
  const modules = await getAllOfflineModules();
  return modules.filter(
    (m) => m.status === "downloaded" || m.status === "downloading"
  ).length;
}

/**
 * Check if user can download another module (max 3).
 */
export async function canDownloadMore(): Promise<boolean> {
  return (await getDownloadedModuleCount()) < MAX_OFFLINE_MODULES;
}

/**
 * Poll a content generation task until complete, failed, or timeout.
 */
async function pollContentStatus(
  taskId: string,
  signal: AbortSignal
): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < POLL_TIMEOUT_MS) {
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");

    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));

    const status = await apiFetch<ContentStatusResponse>(
      `/api/v1/content/status/${taskId}`,
      { signal }
    );

    if (status.status === "complete") return;
    if (status.status === "failed") {
      throw new Error(status.error || "Content generation failed");
    }
  }
  throw new Error("Content generation timed out");
}

/**
 * Fetch a single content item, handling 202 (generating) responses.
 * Returns the content data or null if the content type doesn't exist for this unit.
 */
async function fetchContentItem<T>(
  url: string,
  signal: AbortSignal
): Promise<T | null> {
  try {
    const res = await apiFetch<T | { status: string; task_id: string }>(url, { signal });

    // Handle 202-like generating response
    if (res && typeof res === "object" && "status" in res && "task_id" in res) {
      const generating = res as { status: string; task_id: string };
      if (generating.status === "generating") {
        await pollContentStatus(generating.task_id, signal);
        // Re-fetch after generation completes
        return apiFetch<T>(url, { signal });
      }
    }

    return res as T;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    // 404 means content doesn't exist for this unit — skip it
    if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 404) {
      return null;
    }
    throw err;
  }
}

/**
 * Download a module for offline use.
 *
 * Fetches all units' lessons, quizzes and case studies, then the module's
 * flashcards and its story when one is already written, using existing API
 * endpoints, and stores them in IndexedDB. Each unit becomes usable as soon
 * as its content is downloaded (partial downloads are functional).
 */
export async function downloadModule(
  moduleId: string,
  locale: "fr" | "en",
  options: {
    wifiOnly?: boolean;
    level?: number;
    country?: string;
    onProgress?: DownloadProgressCallback;
  } = {}
): Promise<void> {
  const { wifiOnly = false, level = 1, country = "CI", onProgress } = options;

  // WiFi-only check
  if (wifiOnly) {
    const wifi = isWifiConnection();
    if (wifi === false) {
      throw new Error("WiFi-only download requested but not on WiFi");
    }
  }

  // Check module limit
  const existing = await getOfflineModule(moduleId);
  if (!existing || existing.status !== "downloaded") {
    if (!(await canDownloadMore()) && existing?.status !== "downloading") {
      throw new Error("Maximum offline module limit reached (3)");
    }
  }

  // Set up abort controller
  const abortController = new AbortController();
  activeAbortControllers.set(moduleId, abortController);
  const { signal } = abortController;

  const emit = (progress: DownloadProgress) => onProgress?.(progress);

  try {
    // Step 1: Fetch module structure
    emit({ phase: "fetching_structure", totalUnits: 0, downloadedUnits: 0 });

    const moduleInfo = await apiFetch<ModuleUnitsResponse>(
      `/api/v1/content/modules/${moduleId}/units`,
      { signal }
    );

    const units = moduleInfo.units.sort((a, b) => a.order_index - b.order_index);
    const totalUnits = units.length;
    const estimatedSize = estimateModuleSize(totalUnits);

    // Initialize module record in IndexedDB
    await upsertOfflineModule({
      moduleId,
      status: "downloading",
      totalUnits,
      downloadedUnits: existing?.downloadedUnits ?? 0,
      sizeBytes: estimatedSize,
      updatedAt: Date.now(),
    });

    let downloadedUnits = 0;

    // Step 2: Download each unit's content
    for (const unit of units) {
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");

      const unitId = unit.unit_number;

      // Download lesson
      emit({
        phase: "downloading_content",
        totalUnits,
        downloadedUnits,
        currentUnit: unitId,
        currentContentType: "lesson",
      });

      await downloadUnitContent(
        moduleId, unitId, "lesson",
        `/api/v1/content/lessons/${moduleId}/${unitId}?language=${locale}&level=${level}&country=${country}`,
        locale, signal
      );

      // Download quiz
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");

      emit({
        phase: "downloading_content",
        totalUnits,
        downloadedUnits,
        currentUnit: unitId,
        currentContentType: "quiz",
      });

      await downloadUnitQuiz(moduleId, unitId, locale, level, country, signal);

      // Download case study (only for case-study type units, but try for all)
      if (signal.aborted) throw new DOMException("Aborted", "AbortError");

      emit({
        phase: "downloading_content",
        totalUnits,
        downloadedUnits,
        currentUnit: unitId,
        currentContentType: "case_study",
      });

      await downloadUnitContent(
        moduleId, unitId, "case_study",
        `/api/v1/content/cases/${moduleId}/${unitId}?language=${locale}&level=${level}&country=${country}`,
        locale, signal
      );

      downloadedUnits++;

      // Update progress in IndexedDB
      await upsertOfflineModule({
        moduleId,
        status: "downloading",
        totalUnits,
        downloadedUnits,
        sizeBytes: estimatedSize,
        updatedAt: Date.now(),
      });

      // Pre-warm the SW page cache with the rendered unit page so an offline
      // navigation here is served from cache instead of falling through to
      // /offline.html. The IndexedDB-backed viewer hydrates inside the cached
      // HTML via content-loader.
      await prewarmPage(`/${locale}/modules/${moduleId}/units/${unitId}`);
    }

    // Step 3: Download module-level flashcards
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");

    try {
      const flashcards = await fetchContentItem<unknown>(
        `/api/v1/flashcards/modules/${moduleId}?language=${locale}&level=${level}`,
        signal
      );
      if (flashcards) {
        await upsertOfflineContent({
          unitId: `__module_${moduleId}__`,
          moduleId,
          contentType: "flashcard",
          locale,
          content: flashcards,
          cachedAt: Date.now(),
        });
      }
    } catch {
      // Flashcard download failure is non-fatal
    }

    // Step 4: Save the module story if one is already written. A module has
    // one story covering all its units, written on demand when a learner
    // first opens it, so the download only reads the cache: it never pays
    // for a story nobody asked for, nor waits minutes for one.
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");

    emit({
      phase: "downloading_content",
      totalUnits,
      downloadedUnits,
      currentContentType: "story",
    });

    if ((await downloadModuleStory(moduleId, locale, signal)) !== "none") {
      // So the story page itself opens offline; it then plays the stored
      // copy — this one, or the one loadModuleStory stores when a story not
      // written yet is first opened online.
      await prewarmPage(`/${locale}/modules/${moduleId}/story`);
    }

    // Step 5: Mark module as downloaded
    await upsertOfflineModule({
      moduleId,
      status: "downloaded",
      totalUnits,
      downloadedUnits: totalUnits,
      sizeBytes: estimatedSize,
      downloadedAt: Date.now(),
      updatedAt: Date.now(),
    });

    // Pre-warm the module landing too, so reaching it offline doesn't bounce
    // to /offline.html before the user can navigate to a unit.
    await prewarmPage(`/${locale}/modules/${moduleId}`);

    emit({ phase: "complete", totalUnits, downloadedUnits: totalUnits });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      emit({
        phase: "cancelled",
        totalUnits: 0,
        downloadedUnits: 0,
      });
      return;
    }

    // Mark module as errored (but keep partial content)
    const mod = await getOfflineModule(moduleId);
    if (mod) {
      await upsertOfflineModule({ ...mod, status: "error" });
    }

    emit({
      phase: "error",
      totalUnits: 0,
      downloadedUnits: 0,
      error: err instanceof Error ? err.message : "Download failed",
    });

    throw err;
  } finally {
    activeAbortControllers.delete(moduleId);
  }
}

/**
 * Cancel an in-progress download.
 */
export function cancelDownload(moduleId: string): void {
  const controller = activeAbortControllers.get(moduleId);
  if (controller) {
    controller.abort();
    activeAbortControllers.delete(moduleId);
  }
}

/**
 * Remove a downloaded module and all its cached content.
 */
export async function removeOfflineModule(moduleId: string): Promise<void> {
  cancelDownload(moduleId);
  await deleteOfflineModule(moduleId);
}

// --- Internal helpers ---

/**
 * Store the module's story when the server already has one written.
 *
 * Asks with `generate=false` (contract C-4): a story nobody has opened yet
 * answers 404 `story_not_cached` and nothing is dispatched. A 202
 * "generating" (a learner opened it moments ago) is skipped too, never
 * polled, so a download cannot sit for the minutes a first story takes.
 * 403 (subscribers only), the other 404s (story mode off, no lesson in the
 * module) and 409 (no valid story) are expected skips. Any other failure is
 * non-fatal, like a missing case study.
 *
 * Stored under the module's pseudo-unit key, the one module flashcards use
 * and loadModuleStory reads. Returns "stored"; "later" when the story is not
 * written yet (404 `story_not_cached`, the 202) or could not be fetched now:
 * opening it online later stores it, so its page is still worth pre-warming;
 * "none" when there is nothing to play here (403, the other 404s, 409, a body
 * that is not a story, or a story that could not be stored).
 */
async function downloadModuleStory(
  moduleId: string,
  locale: "fr" | "en",
  signal: AbortSignal
): Promise<"stored" | "later" | "none"> {
  let data: unknown;
  try {
    data = await apiFetch<unknown>(
      moduleStoryPath(moduleId, locale, { generate: false }),
      { signal }
    );
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    const status =
      err && typeof err === "object" ? (err as { status?: unknown }).status : undefined;
    if (status === 404 && storyErrorCode(err) === "story_not_cached") return "later";
    if (status === 403 || status === 404 || status === 409) return "none";
    console.warn(`Failed to download the story of module ${moduleId}:`, err);
    return "later";
  }
  if (isStoryGenerating(data)) return "later";
  // Only a real story document is stored, never an envelope.
  if (!isStoryDocument(data)) return "none";
  try {
    await upsertOfflineContent({
      unitId: `__module_${moduleId}__`,
      moduleId,
      contentType: "story",
      locale,
      content: data,
      cachedAt: Date.now(),
    });
    return "stored";
  } catch (err: unknown) {
    // Non-fatal, like any other content that could not be stored.
    console.warn(`Failed to store the story of module ${moduleId}:`, err);
    return "none";
  }
}

async function downloadUnitContent(
  moduleId: string,
  unitId: string,
  contentType: ContentType,
  url: string,
  locale: "fr" | "en",
  signal: AbortSignal
): Promise<void> {
  try {
    const data = await fetchContentItem<unknown>(url, signal);
    if (data) {
      await upsertOfflineContent({
        unitId,
        moduleId,
        contentType,
        locale,
        content: data,
        cachedAt: Date.now(),
      });
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    // Non-fatal: content may not exist yet, continue with other units
    console.warn(`Failed to download ${contentType} for ${unitId}:`, err);
  }
}

async function downloadUnitQuiz(
  moduleId: string,
  unitId: string,
  locale: "fr" | "en",
  level: number,
  country: string,
  signal: AbortSignal
): Promise<void> {
  const quizBody = JSON.stringify({
    module_id: moduleId,
    unit_id: unitId,
    language: locale,
    country,
    level,
    num_questions: 10,
    force_regenerate: false,
  });

  try {
    const res = await apiFetch<unknown>("/api/v1/quiz/generate", {
      method: "POST",
      signal,
      body: quizBody,
    });

    if (!res) return;

    // Handle 202-like generating response
    if (typeof res === "object" && "status" in (res as Record<string, unknown>) && "task_id" in (res as Record<string, unknown>)) {
      const gen = res as { status: string; task_id: string };
      if (gen.status === "generating") {
        await pollContentStatus(gen.task_id, signal);
        // Re-fetch cached quiz after generation
        const finalQuiz = await apiFetch<unknown>("/api/v1/quiz/generate", {
          method: "POST",
          signal,
          body: quizBody,
        });
        if (finalQuiz) {
          await upsertOfflineContent({
            unitId,
            moduleId,
            contentType: "quiz",
            locale,
            content: finalQuiz,
            cachedAt: Date.now(),
          });
        }
        return;
      }
    }

    await upsertOfflineContent({
      unitId,
      moduleId,
      contentType: "quiz",
      locale,
      content: res,
      cachedAt: Date.now(),
    });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    console.warn(`Failed to download quiz for ${unitId}:`, err);
  }
}
