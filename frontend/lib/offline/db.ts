import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export interface OfflineModule {
  id: string;
  module_id: string;
  status: "pending" | "downloading" | "downloaded" | "error";
  total_units: number;
  downloaded_units: number;
  size_bytes: number;
  last_updated: number;
}

export interface OfflineContent {
  id: string;
  module_id: string;
  unit_id: string;
  content_type: "lesson" | "quiz" | "case_study";
  content: unknown;
  cached_at: number;
  expires_at: number;
}

export interface OfflineAction {
  id: string;
  action_type: "quiz_submission" | "flashcard_rating" | "unit_completion" | "progress_update";
  payload: unknown;
  created_at: number;
  retry_count: number;
  status: "pending" | "syncing" | "failed";
}

interface SantePubliqueDB extends DBSchema {
  offline_modules: {
    key: string;
    value: OfflineModule;
    indexes: {
      by_module_id: string;
      by_status: string;
    };
  };
  offline_content: {
    key: string;
    value: OfflineContent;
    indexes: {
      by_module_id: string;
      by_unit_id: string;
      by_expires_at: number;
    };
  };
  offline_actions: {
    key: string;
    value: OfflineAction;
    indexes: {
      by_status: string;
      by_created_at: number;
    };
  };
}

const DB_NAME = "santepublique-offline";
const DB_VERSION = 1;

let dbInstance: IDBPDatabase<SantePubliqueDB> | null = null;

export async function getDB(): Promise<IDBPDatabase<SantePubliqueDB>> {
  if (dbInstance) return dbInstance;

  dbInstance = await openDB<SantePubliqueDB>(DB_NAME, DB_VERSION, {
    upgrade(db) {
      const modulesStore = db.createObjectStore("offline_modules", {
        keyPath: "id",
      });
      modulesStore.createIndex("by_module_id", "module_id");
      modulesStore.createIndex("by_status", "status");

      const contentStore = db.createObjectStore("offline_content", {
        keyPath: "id",
      });
      contentStore.createIndex("by_module_id", "module_id");
      contentStore.createIndex("by_unit_id", "unit_id");
      contentStore.createIndex("by_expires_at", "expires_at");

      const actionsStore = db.createObjectStore("offline_actions", {
        keyPath: "id",
      });
      actionsStore.createIndex("by_status", "status");
      actionsStore.createIndex("by_created_at", "created_at");
    },
    blocked() {
      dbInstance = null;
    },
    blocking() {
      dbInstance?.close();
      dbInstance = null;
    },
    terminated() {
      dbInstance = null;
    },
  });

  return dbInstance;
}

export async function getOfflineModule(moduleId: string): Promise<OfflineModule | undefined> {
  const db = await getDB();
  const results = await db.getAllFromIndex("offline_modules", "by_module_id", moduleId);
  return results[0];
}

export async function upsertOfflineModule(module: OfflineModule): Promise<void> {
  const db = await getDB();
  await db.put("offline_modules", module);
}

export async function getOfflineContent(unitId: string): Promise<OfflineContent | undefined> {
  const db = await getDB();
  const results = await db.getAllFromIndex("offline_content", "by_unit_id", unitId);
  const now = Date.now();
  return results.find((c) => c.expires_at > now);
}

export async function putOfflineContent(content: OfflineContent): Promise<void> {
  const db = await getDB();
  await db.put("offline_content", content);
}

export async function queueOfflineAction(action: Omit<OfflineAction, "id" | "created_at" | "retry_count" | "status">): Promise<void> {
  const db = await getDB();
  const entry: OfflineAction = {
    ...action,
    id: `action_${Date.now()}_${Math.random().toString(36).slice(2)}`,
    created_at: Date.now(),
    retry_count: 0,
    status: "pending",
  };
  await db.put("offline_actions", entry);
}

export async function getPendingActions(): Promise<OfflineAction[]> {
  const db = await getDB();
  return db.getAllFromIndex("offline_actions", "by_status", "pending");
}

export async function updateActionStatus(id: string, status: OfflineAction["status"], retryCount?: number): Promise<void> {
  const db = await getDB();
  const action = await db.get("offline_actions", id);
  if (!action) return;
  await db.put("offline_actions", {
    ...action,
    status,
    retry_count: retryCount ?? action.retry_count,
  });
}

export async function deleteAction(id: string): Promise<void> {
  const db = await getDB();
  await db.delete("offline_actions", id);
}

export async function clearExpiredContent(): Promise<void> {
  const db = await getDB();
  const now = Date.now();
  const expired = await db.getAllFromIndex("offline_content", "by_expires_at", IDBKeyRange.upperBound(now));
  const tx = db.transaction("offline_content", "readwrite");
  await Promise.all(expired.map((c) => tx.store.delete(c.id)));
  await tx.done;
}
