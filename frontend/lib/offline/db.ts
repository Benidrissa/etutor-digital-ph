const DB_NAME = "santeaof-offline";
const DB_VERSION = 1;

export type ActionType = "quiz_attempt" | "flashcard_review" | "lesson_reading";
export type ActionStatus = "pending" | "synced" | "failed";

export interface OfflineAction {
  id?: number;
  type: ActionType;
  payload: Record<string, unknown>;
  timestamp: number;
  status: ActionStatus;
  retryCount: number;
  serverTimestamp?: number;
}

let dbInstance: IDBDatabase | null = null;

export async function openDB(): Promise<IDBDatabase> {
  if (dbInstance) return dbInstance;

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;

      if (!db.objectStoreNames.contains("offline_actions")) {
        const store = db.createObjectStore("offline_actions", {
          keyPath: "id",
          autoIncrement: true,
        });
        store.createIndex("status", "status", { unique: false });
        store.createIndex("timestamp", "timestamp", { unique: false });
        store.createIndex("type", "type", { unique: false });
      }
    };

    request.onsuccess = (event) => {
      dbInstance = (event.target as IDBOpenDBRequest).result;
      resolve(dbInstance);
    };

    request.onerror = () => {
      reject(request.error);
    };
  });
}

export async function addOfflineAction(
  action: Omit<OfflineAction, "id">
): Promise<number> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readwrite");
    const store = tx.objectStore("offline_actions");
    const req = store.add(action);
    req.onsuccess = () => resolve(req.result as number);
    req.onerror = () => reject(req.error);
  });
}

export async function getPendingActions(): Promise<OfflineAction[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readonly");
    const store = tx.objectStore("offline_actions");
    const index = store.index("status");
    const req = index.getAll("pending");
    req.onsuccess = () => {
      const actions = (req.result as OfflineAction[]).sort(
        (a, b) => a.timestamp - b.timestamp
      );
      resolve(actions);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function getPendingCount(): Promise<number> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readonly");
    const store = tx.objectStore("offline_actions");
    const index = store.index("status");
    const req = index.count("pending");
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function markActionSynced(id: number): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readwrite");
    const store = tx.objectStore("offline_actions");
    const getReq = store.get(id);
    getReq.onsuccess = () => {
      const action = getReq.result as OfflineAction;
      if (!action) {
        resolve();
        return;
      }
      action.status = "synced";
      const putReq = store.put(action);
      putReq.onsuccess = () => resolve();
      putReq.onerror = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

export async function markActionFailed(
  id: number,
  incrementRetry = true
): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readwrite");
    const store = tx.objectStore("offline_actions");
    const getReq = store.get(id);
    getReq.onsuccess = () => {
      const action = getReq.result as OfflineAction;
      if (!action) {
        resolve();
        return;
      }
      if (incrementRetry) {
        action.retryCount += 1;
      }
      const putReq = store.put(action);
      putReq.onsuccess = () => resolve();
      putReq.onerror = () => reject(putReq.error);
    };
    getReq.onerror = () => reject(getReq.error);
  });
}

export async function getSyncedActionCounts(): Promise<
  Record<ActionType, number>
> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readonly");
    const store = tx.objectStore("offline_actions");
    const index = store.index("status");
    const req = index.getAll("synced");
    req.onsuccess = () => {
      const actions = req.result as OfflineAction[];
      const counts: Record<ActionType, number> = {
        quiz_attempt: 0,
        flashcard_review: 0,
        lesson_reading: 0,
      };
      for (const action of actions) {
        counts[action.type] = (counts[action.type] || 0) + 1;
      }
      resolve(counts);
    };
    req.onerror = () => reject(req.error);
  });
}

export async function clearSyncedActions(): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("offline_actions", "readwrite");
    const store = tx.objectStore("offline_actions");
    const index = store.index("status");
    const req = index.getAllKeys("synced");
    req.onsuccess = () => {
      const keys = req.result as number[];
      let deleted = 0;
      if (keys.length === 0) {
        resolve();
        return;
      }
      for (const key of keys) {
        const delReq = store.delete(key);
        delReq.onsuccess = () => {
          deleted++;
          if (deleted === keys.length) resolve();
        };
        delReq.onerror = () => reject(delReq.error);
      }
    };
    req.onerror = () => reject(req.error);
  });
}
