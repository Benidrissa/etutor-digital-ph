/**
 * Background sync manager.
 *
 * Singleton that listens for the `online` event and processes the
 * `offline_actions` queue in FIFO order, mapping each action to its
 * corresponding API endpoint.
 */

import {
  getPendingOfflineActions,
  markOfflineActionSynced,
  clearSyncedActions,
  getOfflineModulesByStatus,
  getOfflineContentByModule,
  upsertOfflineContent,
  REPLAY_REQUESTED_EVENT,
  type OfflineAction,
} from './db';
import {
  apiFetch,
  isQuizChangedError,
  type Quiz,
  type QuizAnswerSubmission,
  type QuizAttemptRequest,
} from '@/lib/api';
import { isPagePrewarmed, prewarmPage, prewarmRetryable } from './prewarm';
import type { QueuedQuizAnswerPayload } from './offline-quiz-scorer';

const PREWARM_V6_DONE_KEY = 'offline_prewarm_v6_done';
const PREWARM_V7_DONE_KEY = 'offline_prewarm_v7_done';
const PREWARM_V8_DONE_KEY = 'offline_prewarm_v8_done';
const PREWARM_V12_DONE_KEY = 'offline_prewarm_v12_done';
// The v12 prewarm's runs so far and the earliest time for the next one (#2692).
export const PREWARM_V12_RUNS_KEY = 'offline_prewarm_v12_runs';
export const PREWARM_V12_NEXT_KEY = 'offline_prewarm_v12_next';
export const PREWARM_V12_MAX_RUNS = 3;
export const PREWARM_V12_BACKOFF_MS = 5 * 60 * 1000;

export type SyncStatus =
  | { state: 'idle' }
  | { state: 'syncing'; current: number; total: number }
  // quizChanged: queued quiz answers dropped because the quiz was regenerated
  // and their revision can no longer be graded (409 quiz_changed).
  | { state: 'complete'; synced: number; quizChanged?: number }
  | { state: 'error'; message: string; synced: number; failed: number; quizChanged?: number };

type ActionOutcome = 'synced' | 'failed' | 'quiz_changed';

/**
 * The POST /quiz/attempt body for a queued offline quiz answer.
 *
 * The queue stores answers as a question_id -> option map (per-question timing
 * is not tracked offline); the endpoint takes a list. content_revision pins
 * the answers to the questions they were given to. Entries queued before it
 * existed have none, and nothing else they hold says which questions they
 * answered: the server grades them only if the quiz has never changed, and
 * otherwise refuses them with 409 quiz_changed (the entry is then dropped and
 * the quiz copy refreshed) rather than grade them against questions the
 * learner never saw.
 */
export function buildQueuedQuizAttemptBody(payload: QueuedQuizAnswerPayload): QuizAttemptRequest {
  const raw = payload.answers as unknown;
  const answers: QuizAnswerSubmission[] = Array.isArray(raw)
    ? (raw as QuizAnswerSubmission[])
    : Object.entries((raw ?? {}) as Record<string, number>).map(([questionId, option]) => ({
        question_id: questionId,
        selected_option: option,
        time_taken_seconds: 0,
      }));
  const body: QuizAttemptRequest = {
    quiz_id: payload.quiz_id,
    answers,
    total_time_seconds: payload.total_time_seconds,
  };
  if (typeof payload.content_revision === 'number') {
    body.content_revision = payload.content_revision;
  }
  return body;
}

export type SyncStatusListener = (status: SyncStatus) => void;

const MAX_RETRIES = 3;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30_000;

/**
 * Delays before each automatic replay that scheduleSync() runs. Short first,
 * so a completion queued on a 2G hiccup reaches the server quickly; then
 * spaced out, so a link that stays bad is not hammered. Past the last one the
 * next `online` event or app start takes over.
 */
export const REPLAY_DELAYS_MS = [5_000, 30_000, 2 * 60_000, 5 * 60_000] as const;

class SyncManager {
  private static instance: SyncManager | null = null;
  private isSyncing = false;
  private listeners = new Set<SyncStatusListener>();
  private onlineHandler: (() => void) | null = null;
  private replayRequestHandler: (() => void) | null = null;
  private started = false;
  private replayTimer: ReturnType<typeof setTimeout> | null = null;

  static getInstance(): SyncManager {
    if (!SyncManager.instance) {
      SyncManager.instance = new SyncManager();
    }
    return SyncManager.instance;
  }

  /** Register the `online` event listener. Call once on app mount. */
  start(): void {
    if (this.started || typeof window === 'undefined') return;
    this.started = true;

    this.onlineHandler = () => {
      this.syncNow();
      this.runV6PrewarmMigration();
      this.runV7PrewarmMigration();
      this.runV8PrewarmMigration();
      this.runV12PrewarmMigration();
    };
    window.addEventListener('online', this.onlineHandler);

    // requestOfflineReplay(): an action was queued while the device still
    // looked online, so no `online` event will replay it.
    this.replayRequestHandler = () => this.scheduleSync();
    window.addEventListener(REPLAY_REQUESTED_EVENT, this.replayRequestHandler);

    // Also run on startup in case the app is already online — covers the
    // common case where a v5/v6 user opens the app online without a network
    // toggle. The same goes for the queue: an action queued while the device
    // still looked online (a POST that died on 2G) never sees an `online`
    // event, so it is replayed when the app opens.
    if (typeof navigator !== 'undefined' && navigator.onLine) {
      this.syncNow().catch(() => {
        // best-effort; the next `online` event or replay request retries
      });
      this.runV6PrewarmMigration();
      this.runV7PrewarmMigration();
      this.runV8PrewarmMigration();
      this.runV12PrewarmMigration();
    }
  }

  /** Clean up event listener. */
  stop(): void {
    if (this.onlineHandler) {
      window.removeEventListener('online', this.onlineHandler);
      this.onlineHandler = null;
    }
    if (this.replayRequestHandler) {
      window.removeEventListener(REPLAY_REQUESTED_EVENT, this.replayRequestHandler);
      this.replayRequestHandler = null;
    }
    this.cancelScheduledSync();
    this.started = false;
  }

  /**
   * Replay the queue soon, without waiting for an `online` event.
   *
   * On 2G `navigator.onLine` often stays true while requests die. An action
   * queued then gets no `online` event — the device never went offline — so
   * it would sit in IndexedDB until the connection flips. This retries the
   * queue on the REPLAY_DELAYS_MS backoff until it drains or the schedule
   * runs out. A call while a replay is already scheduled is folded into it.
   * A replay that comes due while the device is offline is left to the
   * `online` handler.
   */
  scheduleSync(attempt = 0): void {
    if (typeof window === 'undefined') return;
    if (this.replayTimer !== null || attempt >= REPLAY_DELAYS_MS.length) return;
    this.replayTimer = setTimeout(() => {
      this.replayTimer = null;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;
      this.syncNow()
        .then(() => this.getPendingCount())
        .then((pending) => {
          if (pending > 0) this.scheduleSync(attempt + 1);
        })
        .catch(() => this.scheduleSync(attempt + 1));
    }, REPLAY_DELAYS_MS[attempt]);
  }

  /** Drop a replay scheduled by scheduleSync(), if any. */
  cancelScheduledSync(): void {
    if (this.replayTimer !== null) {
      clearTimeout(this.replayTimer);
      this.replayTimer = null;
    }
  }

  /** Subscribe to sync status changes. Returns an unsubscribe function. */
  onStatusChange(listener: SyncStatusListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Get count of pending (unsynced) actions. */
  async getPendingCount(): Promise<number> {
    const actions = await getPendingOfflineActions();
    return actions.length;
  }

  /** Process the pending actions queue. Safe to call multiple times. */
  async syncNow(): Promise<{ synced: number; failed: number }> {
    if (this.isSyncing) return { synced: 0, failed: 0 };
    this.isSyncing = true;
    // Released whatever happens: an IndexedDB error must not wedge the queue
    // shut for the rest of the session.
    try {
      const actions = await getPendingOfflineActions();
      if (actions.length === 0) {
        return { synced: 0, failed: 0 };
      }

      let synced = 0;
      let failed = 0;
      let quizChanged = 0;

      this.emit({ state: 'syncing', current: 0, total: actions.length });

      for (let i = 0; i < actions.length; i++) {
        const action = actions[i];
        this.emit({ state: 'syncing', current: i + 1, total: actions.length });

        const outcome = await this.processAction(action);
        if (outcome === 'synced') {
          synced++;
        } else if (outcome === 'quiz_changed') {
          quizChanged++;
        } else {
          failed++;
        }
      }

      // Clean up synced actions
      await clearSyncedActions();

      if (failed > 0) {
        this.emit({
          state: 'error',
          message: `${failed} actions failed`,
          synced,
          failed,
          quizChanged,
        });
      } else {
        this.emit({ state: 'complete', synced, quizChanged });
      }

      return { synced, failed };
    } finally {
      this.isSyncing = false;
    }
  }

  /**
   * One-shot migration for users who downloaded a module under SW v5.
   * Their IndexedDB has the unit content but the v6 SW page cache is empty,
   * so an offline navigation falls through to /offline.html. This re-runs
   * the page pre-warm once so they get the same offline experience as
   * users who download fresh under v6.
   */
  async runV6PrewarmMigration(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      if (localStorage.getItem(PREWARM_V6_DONE_KEY)) return;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;

      const modules = await getOfflineModulesByStatus('downloaded');
      for (const mod of modules) {
        const entries = await getOfflineContentByModule(mod.moduleId);
        const flashcardKey = `__module_${mod.moduleId}__`;
        const seen = new Set<string>();
        for (const entry of entries) {
          if (entry.unitId === flashcardKey) continue;
          const key = `${entry.locale}|${entry.unitId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          await prewarmPage(
            `/${entry.locale}/modules/${mod.moduleId}/units/${entry.unitId}`,
          );
        }
        // Pre-warm the module landing in each locale we have content for.
        const locales = new Set(entries.map((e) => e.locale));
        for (const loc of locales) {
          await prewarmPage(`/${loc}/modules/${mod.moduleId}`);
        }
      }
      localStorage.setItem(PREWARM_V6_DONE_KEY, '1');
    } catch {
      // best-effort; failure must not break sync
    }
  }

  /**
   * One-shot migration for users who downloaded a module under SW v6.
   * The v7 cache-version bump (adding progress no-cache) renamed the pages
   * cache from `pages-v6-offline-routes` to `pages-v7-status-no-cache`.
   * Without this, previously-prewarm pages are invisible to the v7 SW and
   * offline navigation falls through to /offline.html.
   */
  async runV7PrewarmMigration(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      if (localStorage.getItem(PREWARM_V7_DONE_KEY)) return;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;

      const modules = await getOfflineModulesByStatus('downloaded');
      for (const mod of modules) {
        const entries = await getOfflineContentByModule(mod.moduleId);
        const flashcardKey = `__module_${mod.moduleId}__`;
        const seen = new Set<string>();
        for (const entry of entries) {
          if (entry.unitId === flashcardKey) continue;
          const key = `${entry.locale}|${entry.unitId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          await prewarmPage(
            `/${entry.locale}/modules/${mod.moduleId}/units/${entry.unitId}`,
          );
        }
        const locales = new Set(entries.map((e) => e.locale));
        for (const loc of locales) {
          await prewarmPage(`/${loc}/modules/${mod.moduleId}`);
        }
      }
      localStorage.setItem(PREWARM_V7_DONE_KEY, '1');
    } catch {
      // best-effort; failure must not break sync
    }
  }

  /**
   * One-shot migration for users who downloaded a module under SW v7.
   * The v8 cache-version bump (dropping answer-bearing summative quiz GET
   * bodies, #2550) renamed the pages cache from `pages-v7-status-no-cache`
   * to `pages-v8-summative-safe`. Without this, previously-prewarmed pages
   * are invisible to the v8 SW and offline navigation falls through to
   * /offline.html.
   */
  async runV8PrewarmMigration(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      if (localStorage.getItem(PREWARM_V8_DONE_KEY)) return;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;

      const modules = await getOfflineModulesByStatus('downloaded');
      for (const mod of modules) {
        const entries = await getOfflineContentByModule(mod.moduleId);
        const flashcardKey = `__module_${mod.moduleId}__`;
        const seen = new Set<string>();
        for (const entry of entries) {
          if (entry.unitId === flashcardKey) continue;
          const key = `${entry.locale}|${entry.unitId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          await prewarmPage(
            `/${entry.locale}/modules/${mod.moduleId}/units/${entry.unitId}`,
          );
        }
        const locales = new Set(entries.map((e) => e.locale));
        for (const loc of locales) {
          await prewarmPage(`/${loc}/modules/${mod.moduleId}`);
        }
      }
      localStorage.setItem(PREWARM_V8_DONE_KEY, '1');
    } catch {
      // best-effort; failure must not break sync
    }
  }

  /**
   * One-shot migration for users who downloaded a module before SW v12.
   * The v10 bump (the story media cache, #2681/#2682), the v12 bump (the
   * story player fixes, #2688) and the v12 bump (the AI read-aloud voice,
   * #2704) renamed the pages cache, now `pages-v12-story-voice`. Without this, previously-prewarmed pages, the
   * module story page among them, are invisible to the SW and an offline
   * navigation falls through to /offline.html.
   *
   * It marks itself done once every page is either stored or failed for
   * good (a unit removed: 404; storage full). Only a page that may still come
   * (the link dropped, a 5xx) brings it back, at most PREWARM_V12_MAX_RUNS
   * times in all, with a growing wait persisted between runs, and a page
   * stored already is never fetched again: on 2G a dead page must not cost
   * every module's pages on each start (#2692). Overlapping calls (an
   * `online` event during a run) share the run in progress.
   */
  runV12PrewarmMigration(): Promise<void> {
    if (!this.v12Run) {
      this.v12Run = this.prewarmV12().finally(() => {
        this.v12Run = null;
      });
    }
    return this.v12Run;
  }

  private v12Run: Promise<void> | null = null;

  private async prewarmV12(): Promise<void> {
    if (typeof window === 'undefined') return;
    try {
      if (localStorage.getItem(PREWARM_V12_DONE_KEY)) return;
      if (typeof navigator !== 'undefined' && !navigator.onLine) return;
      const runs = Number(localStorage.getItem(PREWARM_V12_RUNS_KEY)) || 0;
      const notBefore = Number(localStorage.getItem(PREWARM_V12_NEXT_KEY)) || 0;
      if (Date.now() < notBefore) return;

      let retry = false;
      const warm = async (url: string) => {
        if (await isPagePrewarmed(url)) return;
        if (prewarmRetryable(await prewarmPage(url))) retry = true;
      };
      const modules = await getOfflineModulesByStatus('downloaded');
      for (const mod of modules) {
        const entries = await getOfflineContentByModule(mod.moduleId);
        const moduleKey = `__module_${mod.moduleId}__`;
        const seen = new Set<string>();
        for (const entry of entries) {
          if (entry.unitId === moduleKey) continue;
          const key = `${entry.locale}|${entry.unitId}`;
          if (seen.has(key)) continue;
          seen.add(key);
          await warm(`/${entry.locale}/modules/${mod.moduleId}/units/${entry.unitId}`);
        }
        const locales = new Set(entries.map((e) => e.locale));
        for (const loc of locales) {
          await warm(`/${loc}/modules/${mod.moduleId}`);
        }
        // The module story page, where a story was saved with the module.
        const storyLocales = new Set(
          entries.filter((e) => e.contentType === 'story').map((e) => e.locale),
        );
        for (const loc of storyLocales) {
          await warm(`/${loc}/modules/${mod.moduleId}/story`);
        }
      }
      const run = runs + 1;
      if (!retry || run >= PREWARM_V12_MAX_RUNS) {
        localStorage.setItem(PREWARM_V12_DONE_KEY, '1');
        localStorage.removeItem(PREWARM_V12_RUNS_KEY);
        localStorage.removeItem(PREWARM_V12_NEXT_KEY);
      } else {
        localStorage.setItem(PREWARM_V12_RUNS_KEY, String(run));
        localStorage.setItem(
          PREWARM_V12_NEXT_KEY,
          String(Date.now() + PREWARM_V12_BACKOFF_MS * 4 ** (run - 1)),
        );
      }
    } catch {
      // best-effort; failure must not break sync
    }
  }

  // --- Private ---

  private emit(status: SyncStatus): void {
    for (const listener of this.listeners) {
      try {
        listener(status);
      } catch {
        // Listener errors are non-fatal
      }
    }
  }

  private async processAction(action: OfflineAction): Promise<ActionOutcome> {
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        await this.sendAction(action);
        if (action.id !== undefined) {
          await markOfflineActionSynced(action.id);
        }
        return 'synced';
      } catch (err: unknown) {
        // 401: auth expired — stop retrying entirely
        if (isHttpStatus(err, 401)) {
          console.warn('Sync: auth expired, skipping action', action.id);
          return 'failed';
        }

        // 409 quiz_changed: the quiz was regenerated and the revision these
        // answers were given to cannot be graded any more. Retrying cannot
        // help, so drop them, refresh the offline copy of the quiz so the next
        // attempt uses the current questions, and let the learner know.
        if (action.actionType === 'quiz_answer' && isQuizChangedError(err)) {
          console.warn('Sync: quiz changed since it was answered offline', action.id);
          if (action.id !== undefined) {
            await markOfflineActionSynced(action.id);
          }
          await refreshOfflineQuiz(action.payload as QueuedQuizAnswerPayload);
          return 'quiz_changed';
        }

        // 409: conflict (duplicate) — treat as success
        if (isHttpStatus(err, 409)) {
          if (action.id !== undefined) {
            await markOfflineActionSynced(action.id);
          }
          return 'synced';
        }

        // 4xx (except 401/409): permanent error, don't retry
        if (isHttpStatus(err, 400) || isHttpStatus(err, 403) || isHttpStatus(err, 404) || isHttpStatus(err, 422)) {
          console.warn(`Sync: permanent error for action ${action.id}:`, err);
          return 'failed';
        }

        // Transient error: exponential backoff
        if (attempt < MAX_RETRIES - 1) {
          const delay = Math.min(
            BACKOFF_BASE_MS * Math.pow(2, attempt),
            BACKOFF_MAX_MS
          );
          await new Promise((r) => setTimeout(r, delay));
        }
      }
    }

    console.warn(`Sync: action ${action.id} failed after ${MAX_RETRIES} retries`);
    return 'failed';
  }

  private async sendAction(action: OfflineAction): Promise<void> {
    const payload = action.payload as Record<string, unknown>;

    switch (action.actionType) {
      case 'quiz_answer':
        await apiFetch('/api/v1/quiz/attempt', {
          method: 'POST',
          body: JSON.stringify(buildQueuedQuizAttemptBody(action.payload as QueuedQuizAnswerPayload)),
        });
        break;

      case 'flashcard_review':
        await apiFetch(`/api/v1/flashcards/${payload.card_id}/review`, {
          method: 'POST',
          body: JSON.stringify({
            rating: payload.rating,
          }),
        });
        break;

      case 'lesson_complete':
        await apiFetch('/api/v1/progress/lesson-access', {
          method: 'POST',
          body: JSON.stringify({
            module_id: payload.module_id,
            lesson_id: payload.lesson_id,
            time_spent_seconds: payload.time_spent_seconds,
            completion_percentage: payload.completion_percentage,
          }),
        });
        break;

      case 'case_study_complete':
        await apiFetch('/api/v1/progress/complete-lesson', {
          method: 'POST',
          body: JSON.stringify({
            module_id: payload.module_id,
            unit_id: payload.unit_id,
          }),
        });
        break;

      default:
        console.warn(`Sync: unknown action type: ${action.actionType}`);
    }
  }
}

/** Best effort: replace the offline copy of a quiz with its current version. */
async function refreshOfflineQuiz(payload: QueuedQuizAnswerPayload): Promise<void> {
  try {
    const fresh = await apiFetch<Quiz>(`/api/v1/quiz/${payload.quiz_id}`);
    await upsertOfflineContent({
      unitId: payload.unit_id ?? fresh.unit_id,
      moduleId: payload.module_id ?? fresh.module_id,
      contentType: 'quiz',
      locale: fresh.language === 'en' ? 'en' : 'fr',
      content: fresh,
      cachedAt: Date.now(),
    });
  } catch {
    // The next online load refreshes it anyway.
  }
}

function isHttpStatus(err: unknown, status: number): boolean {
  return (
    err !== null &&
    typeof err === 'object' &&
    'status' in err &&
    (err as { status: number }).status === status
  );
}

export { SyncManager };
