'use client';

export interface OfflineBundleUnit {
  unit_id: string;
  unit_number: string;
  order_index: number;
  title_fr: string;
  title_en: string;
  estimated_minutes: number;
  size_bytes: number;
  content_ids: {
    lesson: string | null;
    quiz: string | null;
    case_study: string | null;
  };
  image_urls: string[];
}

export interface OfflineBundleResponse {
  module_id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
  total_size_bytes: number;
  units: OfflineBundleUnit[];
}

export type UnitDownloadStatus = 'pending' | 'downloading' | 'done' | 'error';

export interface OfflineModuleRecord {
  module_id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
  total_size_bytes: number;
  downloaded_at: number;
  units: Array<
    OfflineBundleUnit & {
      download_status: UnitDownloadStatus;
      downloaded_bytes: number;
    }
  >;
}

const DB_NAME = 'santepublique-offline';
const DB_VERSION = 1;
const STORE_MODULES = 'offline_modules';

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_MODULES)) {
        db.createObjectStore(STORE_MODULES, { keyPath: 'module_id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function getOfflineModule(
  moduleId: string,
): Promise<OfflineModuleRecord | undefined> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_MODULES, 'readonly');
    const req = tx.objectStore(STORE_MODULES).get(moduleId);
    req.onsuccess = () => resolve(req.result as OfflineModuleRecord | undefined);
    req.onerror = () => reject(req.error);
  });
}

export async function getAllOfflineModules(): Promise<OfflineModuleRecord[]> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_MODULES, 'readonly');
    const req = tx.objectStore(STORE_MODULES).getAll();
    req.onsuccess = () => resolve(req.result as OfflineModuleRecord[]);
    req.onerror = () => reject(req.error);
  });
}

export async function saveOfflineModule(record: OfflineModuleRecord): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_MODULES, 'readwrite');
    const req = tx.objectStore(STORE_MODULES).put(record);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

export async function deleteOfflineModule(moduleId: string): Promise<void> {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_MODULES, 'readwrite');
    const req = tx.objectStore(STORE_MODULES).delete(moduleId);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
  });
}

export async function updateUnitStatus(
  moduleId: string,
  unitId: string,
  status: UnitDownloadStatus,
  downloadedBytes?: number,
): Promise<void> {
  const record = await getOfflineModule(moduleId);
  if (!record) return;
  record.units = record.units.map((u) =>
    u.unit_id === unitId
      ? {
          ...u,
          download_status: status,
          downloaded_bytes: downloadedBytes ?? u.downloaded_bytes,
        }
      : u,
  );
  await saveOfflineModule(record);
}

export function getModuleOfflinePercent(record: OfflineModuleRecord): number {
  if (!record.units.length) return 0;
  const done = record.units.filter((u) => u.download_status === 'done').length;
  return Math.round((done / record.units.length) * 100);
}

export function isModuleFullyOffline(record: OfflineModuleRecord): boolean {
  return record.units.length > 0 && record.units.every((u) => u.download_status === 'done');
}
