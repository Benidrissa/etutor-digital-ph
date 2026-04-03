import { openDB, type DBSchema, type IDBPDatabase } from "idb";

export type ModuleDownloadStatus =
  | "not_downloaded"
  | "downloading"
  | "downloaded"
  | "error";

export type ContentType = "lesson" | "quiz" | "case_study" | "flashcard";

export type ActionType =
  | "lesson_complete"
  | "quiz_answer"
  | "flashcard_review"
  | "case_study_complete";

export interface OfflineModule {
  moduleId: string;
  status: ModuleDownloadStatus;
  totalUnits: number;
  downloadedUnits: number;
  sizeBytes: number;
  downloadedAt?: number;
  updatedAt: number;
}

export interface OfflineContent {
  unitId: string;
  moduleId: string;
  contentType: ContentType;
  locale: "fr" | "en";
  content: unknown;
  cachedAt: number;
  expiresAt?: number;
}

export interface OfflineAction {
  id?: number;
  actionType: ActionType;
  payload: unknown;
  createdAt: number;
  synced: boolean;
  syncedAt?: number;
}

interface SantePubliqueDB extends DBSchema {
  offline_modules: {
    key: string;
    value: OfflineModule;
    indexes: { by_status: ModuleDownloadStatus };
  };
  offline_content: {
    key: [string, string];
    value: OfflineContent;
    indexes: {
      by_module: string;
      by_content_type: ContentType;
    };
  };
  offline_actions: {
    key: number;
    value: OfflineAction;
    indexes: { by_synced: number };
  };
}

const DB_NAME = "santepublique-offline";
const DB_VERSION = 2;

let dbInstance: IDBPDatabase<SantePubliqueDB> | null = null;

export async function getDB(): Promise<IDBPDatabase<SantePubliqueDB>> {
  if (dbInstance) return dbInstance;

  dbInstance = await openDB<SantePubliqueDB>(DB_NAME, DB_VERSION, {
    upgrade(db, oldVersion) {
      if (oldVersion < 1) {
        const modulesStore = db.createObjectStore("offline_modules", {
          keyPath: "moduleId",
        });
        modulesStore.createIndex("by_status", "status");

        const actionsStore = db.createObjectStore("offline_actions", {
          keyPath: "id",
          autoIncrement: true,
        });
        actionsStore.createIndex("by_synced", "synced");
      }

      if (oldVersion < 2) {
        if (db.objectStoreNames.contains("offline_content")) {
          db.deleteObjectStore("offline_content");
        }
        const contentStore = db.createObjectStore("offline_content", {
          keyPath: ["unitId", "locale"],
        });
        contentStore.createIndex("by_module", "moduleId");
        contentStore.createIndex("by_content_type", "contentType");
      }
    },
  });

  return dbInstance;
}

export async function getOfflineModule(
  moduleId: string
): Promise<OfflineModule | undefined> {
  const db = await getDB();
  return db.get("offline_modules", moduleId);
}

export async function upsertOfflineModule(
  module: OfflineModule
): Promise<void> {
  const db = await getDB();
  await db.put("offline_modules", { ...module, updatedAt: Date.now() });
}

export async function getAllOfflineModules(): Promise<OfflineModule[]> {
  const db = await getDB();
  return db.getAll("offline_modules");
}

export async function getOfflineModulesByStatus(
  status: ModuleDownloadStatus
): Promise<OfflineModule[]> {
  const db = await getDB();
  return db.getAllFromIndex("offline_modules", "by_status", status);
}

export async function getOfflineContent(
  unitId: string,
  locale: "fr" | "en"
): Promise<OfflineContent | undefined> {
  const db = await getDB();
  return db.get("offline_content", [unitId, locale]);
}

export async function upsertOfflineContent(
  content: OfflineContent
): Promise<void> {
  const db = await getDB();
  await db.put("offline_content", content);
}

export async function getOfflineContentByModule(
  moduleId: string
): Promise<OfflineContent[]> {
  const db = await getDB();
  return db.getAllFromIndex("offline_content", "by_module", moduleId);
}

export async function deleteOfflineModule(moduleId: string): Promise<void> {
  const db = await getDB();
  const tx = db.transaction(
    ["offline_modules", "offline_content"],
    "readwrite"
  );
  await tx.objectStore("offline_modules").delete(moduleId);
  const contentIndex = tx
    .objectStore("offline_content")
    .index("by_module");
  let cursor = await contentIndex.openCursor(moduleId);
  while (cursor) {
    await cursor.delete();
    cursor = await cursor.continue();
  }
  await tx.done;
}

export async function addOfflineAction(
  action: Omit<OfflineAction, "id" | "createdAt" | "synced">
): Promise<number> {
  const db = await getDB();
  return db.add("offline_actions", {
    ...action,
    createdAt: Date.now(),
    synced: false,
  });
}

export async function getPendingOfflineActions(): Promise<OfflineAction[]> {
  const db = await getDB();
  return db.getAllFromIndex("offline_actions", "by_synced", 0);
}

export async function markOfflineActionSynced(id: number): Promise<void> {
  const db = await getDB();
  const action = await db.get("offline_actions", id);
  if (action) {
    await db.put("offline_actions", {
      ...action,
      synced: true,
      syncedAt: Date.now(),
    });
  }
}

export async function clearSyncedActions(): Promise<void> {
  const db = await getDB();
  const synced = await db.getAllFromIndex("offline_actions", "by_synced", 1);
  const tx = db.transaction("offline_actions", "readwrite");
  for (const action of synced) {
    if (action.id !== undefined) {
      await tx.store.delete(action.id);
    }
  }
  await tx.done;
}
