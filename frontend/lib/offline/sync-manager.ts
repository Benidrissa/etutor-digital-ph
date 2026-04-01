import {
  getPendingActions,
  getPendingCount,
  markActionSynced,
  markActionFailed,
  getSyncedActionCounts,
  clearSyncedActions,
  type ActionType,
  type OfflineAction,
} from "./db";

export type SyncState = "idle" | "syncing" | "error";

export interface SyncStatus {
  state: SyncState;
  pendingCount: number;
  lastSyncedCounts: Record<ActionType, number> | null;
}

type SyncStatusListener = (status: SyncStatus) => void;

const API_ENDPOINTS: Record<ActionType, string> = {
  quiz_attempt: "/api/v1/quiz/lesson-validation/submit",
  flashcard_review: "/api/v1/flashcards/review",
  lesson_reading: "/api/v1/progress/lesson-reading",
};

const MAX_RETRY_COUNT = 5;
const BASE_BACKOFF_MS = 1000;

function getBackoffDelay(retryCount: number): number {
  return Math.min(BASE_BACKOFF_MS * Math.pow(2, retryCount), 30000);
}

async function syncAction(action: OfflineAction): Promise<boolean> {
  const endpoint = API_ENDPOINTS[action.type];
  if (!endpoint) return false;

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...action.payload,
        client_timestamp: action.timestamp,
      }),
    });

    if (response.ok) {
      return true;
    }

    if (response.status >= 400 && response.status < 500) {
      return false;
    }

    return false;
  } catch {
    return false;
  }
}

class SyncManager {
  private listeners: Set<SyncStatusListener> = new Set();
  private state: SyncState = "idle";
  private pendingCount = 0;
  private lastSyncedCounts: Record<ActionType, number> | null = null;
  private isSyncing = false;
  private retryTimeouts: Map<number, ReturnType<typeof setTimeout>> = new Map();

  constructor() {
    if (typeof window !== "undefined") {
      window.addEventListener("online", this.handleOnline);
      this.refreshPendingCount();
    }
  }

  destroy() {
    if (typeof window !== "undefined") {
      window.removeEventListener("online", this.handleOnline);
    }
    for (const timeout of this.retryTimeouts.values()) {
      clearTimeout(timeout);
    }
    this.retryTimeouts.clear();
  }

  private handleOnline = () => {
    this.sync();
  };

  subscribe(listener: SyncStatusListener): () => void {
    this.listeners.add(listener);
    listener(this.getStatus());
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    const status = this.getStatus();
    for (const listener of this.listeners) {
      listener(status);
    }
  }

  getStatus(): SyncStatus {
    return {
      state: this.state,
      pendingCount: this.pendingCount,
      lastSyncedCounts: this.lastSyncedCounts,
    };
  }

  async refreshPendingCount() {
    try {
      this.pendingCount = await getPendingCount();
      this.notify();
    } catch {
      // ignore DB errors silently
    }
  }

  async sync(): Promise<void> {
    if (this.isSyncing) return;
    if (typeof window !== "undefined" && !navigator.onLine) return;

    this.isSyncing = true;
    this.state = "syncing";
    this.notify();

    try {
      const pending = await getPendingActions();

      if (pending.length === 0) {
        this.state = "idle";
        this.isSyncing = false;
        this.notify();
        return;
      }

      let anyFailed = false;

      for (const action of pending) {
        if (action.id === undefined) continue;
        if (action.retryCount >= MAX_RETRY_COUNT) continue;

        const success = await syncAction(action);

        if (success) {
          await markActionSynced(action.id);
        } else {
          await markActionFailed(action.id);
          anyFailed = true;

          const delay = getBackoffDelay(action.retryCount + 1);
          const timeoutId = setTimeout(() => {
            this.retryTimeouts.delete(action.id!);
            if (typeof window !== "undefined" && navigator.onLine) {
              this.sync();
            }
          }, delay);
          this.retryTimeouts.set(action.id, timeoutId);
        }
      }

      const syncedCounts = await getSyncedActionCounts();
      const hasSynced = Object.values(syncedCounts).some((c) => c > 0);
      if (hasSynced) {
        this.lastSyncedCounts = syncedCounts;
        await clearSyncedActions();
      }

      this.pendingCount = await getPendingCount();
      this.state = anyFailed ? "error" : "idle";
    } catch {
      this.state = "error";
    } finally {
      this.isSyncing = false;
      this.notify();
    }
  }
}

let syncManagerInstance: SyncManager | null = null;

export function getSyncManager(): SyncManager {
  if (!syncManagerInstance) {
    syncManagerInstance = new SyncManager();
  }
  return syncManagerInstance;
}

export { SyncManager };
