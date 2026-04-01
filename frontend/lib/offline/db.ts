'use client';

export type UnitDownloadStatus = 'not_downloaded' | 'downloading' | 'downloaded' | 'error';

export interface OfflineUnit {
  unitId: string;
  unitNumber: string;
  titleFr: string;
  titleEn: string;
  estimatedMinutes: number;
  orderIndex: number;
  status: UnitDownloadStatus;
  lessonContentId: string | null;
  quizContentId: string | null;
  caseStudyContentId: string | null;
  lessonData: unknown | null;
  quizData: unknown | null;
  caseStudyData: unknown | null;
  downloadedAt: number | null;
}

export interface OfflineModule {
  moduleId: string;
  moduleNumber: number;
  titleFr: string;
  titleEn: string;
  level: number;
  estimatedHours: number;
  estimatedSizeBytes: number;
  units: OfflineUnit[];
  downloadedAt: number | null;
  lastUpdated: number;
}

const DB_NAME = 'santepublique-offline';
const DB_VERSION = 1;
const MODULES_STORE = 'offline_modules';

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;
      if (!db.objectStoreNames.contains(MODULES_STORE)) {
        db.createObjectStore(MODULES_STORE, { keyPath: 'moduleId' });
      }
    };
    request.onsuccess = (event) => resolve((event.target as IDBOpenDBRequest).result);
    request.onerror = () => reject(request.error);
  });
  return dbPromise;
}

export async function getOfflineModule(moduleId: string): Promise<OfflineModule | null> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(MODULES_STORE, 'readonly');
    const req = tx.objectStore(MODULES_STORE).get(moduleId);
    req.onsuccess = () => resolve((req.result as OfflineModule) ?? null);
    req.onerror = () => reject(req.error);
  });
}

export async function getAllOfflineModules(): Promise<OfflineModule[]> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(MODULES_STORE, 'readonly');
    const req = tx.objectStore(MODULES_STORE).getAll();
    req.onsuccess = () => resolve((req.result as OfflineModule[]) ?? []);
    req.onerror = () => reject(req.error);
  });
}

export async function saveOfflineModule(module: OfflineModule): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(MODULES_STORE, 'readwrite');
    const req = tx.objectStore(MODULES_STORE).put(module);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

export async function deleteOfflineModule(moduleId: string): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(MODULES_STORE, 'readwrite');
    const req = tx.objectStore(MODULES_STORE).delete(moduleId);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

export async function updateUnitStatus(
  moduleId: string,
  unitId: string,
  patch: Partial<OfflineUnit>
): Promise<void> {
  const offlineMod = await getOfflineModule(moduleId);
  if (!offlineMod) return;
  offlineMod.units = offlineMod.units.map((u) =>
    u.unitId === unitId ? { ...u, ...patch } : u
  );
  offlineMod.lastUpdated = Date.now();
  await saveOfflineModule(offlineMod);
}

export function getDownloadedUnitCount(module: OfflineModule): number {
  return module.units.filter((u) => u.status === 'downloaded').length;
}

export function getModuleDownloadPercent(module: OfflineModule): number {
  if (module.units.length === 0) return 0;
  return Math.round((getDownloadedUnitCount(module) / module.units.length) * 100);
}

export function isModuleFullyDownloaded(module: OfflineModule): boolean {
  return (
    module.units.length > 0 &&
    module.units.every((u) => u.status === 'downloaded')
  );
}
