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
  type OfflineAction,
} from './db';
import { apiFetch } from '@/lib/api';
import { prewarmPage } from './download-manager';

const PREWARM_V6_DONE_KEY = 'offline_prewarm_v6_done';

export type SyncStatus =
  | { state: 'idle' }
  | { state: 'syncing'; current: number; total: number }
  | { state: 'complete'; synced: number }
  | { state: 'error'; message: string; synced: number; failed: number };

export type SyncStatusListener = (status: SyncStatus) => void;

const MAX_RETRIES = 3;
const BACKOFF_BASE_MS = 1000;
const BACKOFF_MAX_MS = 30_000;

class SyncManager {
  private static instance: SyncManager | null = null;
  private isSyncing = false;
  private listeners = new Set<SyncStatusListener>();
  private onlineHandler: (() => void) | null = null;
  private started = false;

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
    };
    window.addEventListener('online', this.onlineHandler);

    // Also run on startup in case the app is already online — covers the
    // common case where a v5 user opens the app online without a network
    // toggle.
    if (typeof navigator !== 'undefined' && navigator.onLine) {
      this.runV6PrewarmMigration();
    }
  }

  /** Clean up event listener. */
  stop(): void {
    if (this.onlineHandler) {
      window.removeEventListener('online', this.onlineHandler);
      this.onlineHandler = null;
    }
    this.started = false;
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

    const actions = await getPendingOfflineActions();
    if (actions.length === 0) {
      this.isSyncing = false;
      return { synced: 0, failed: 0 };
    }

    let synced = 0;
    let failed = 0;

    this.emit({ state: 'syncing', current: 0, total: actions.length });

    for (let i = 0; i < actions.length; i++) {
      const action = actions[i];
      this.emit({ state: 'syncing', current: i + 1, total: actions.length });

      const success = await this.processAction(action);
      if (success) {
        synced++;
      } else {
        failed++;
      }
    }

    // Clean up synced actions
    await clearSyncedActions();

    if (failed > 0) {
      this.emit({ state: 'error', message: `${failed} actions failed`, synced, failed });
    } else {
      this.emit({ state: 'complete', synced });
    }

    this.isSyncing = false;
    return { synced, failed };
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

  private async processAction(action: OfflineAction): Promise<boolean> {
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        await this.sendAction(action);
        if (action.id !== undefined) {
          await markOfflineActionSynced(action.id);
        }
        return true;
      } catch (err: unknown) {
        // 401: auth expired — stop retrying entirely
        if (isHttpStatus(err, 401)) {
          console.warn('Sync: auth expired, skipping action', action.id);
          return false;
        }

        // 409: conflict (duplicate) — treat as success
        if (isHttpStatus(err, 409)) {
          if (action.id !== undefined) {
            await markOfflineActionSynced(action.id);
          }
          return true;
        }

        // 4xx (except 401/409): permanent error, don't retry
        if (isHttpStatus(err, 400) || isHttpStatus(err, 403) || isHttpStatus(err, 404) || isHttpStatus(err, 422)) {
          console.warn(`Sync: permanent error for action ${action.id}:`, err);
          return false;
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
    return false;
  }

  private async sendAction(action: OfflineAction): Promise<void> {
    const payload = action.payload as Record<string, unknown>;

    switch (action.actionType) {
      case 'quiz_answer':
        await apiFetch('/api/v1/quiz/attempt', {
          method: 'POST',
          body: JSON.stringify({
            quiz_id: payload.quiz_id,
            answers: payload.answers,
            total_time_seconds: payload.total_time_seconds,
          }),
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

function isHttpStatus(err: unknown, status: number): boolean {
  return (
    err !== null &&
    typeof err === 'object' &&
    'status' in err &&
    (err as { status: number }).status === status
  );
}

export { SyncManager };
