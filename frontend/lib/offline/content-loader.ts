const DB_NAME = 'santeaof-offline';
const DB_VERSION = 1;

const STORES = {
  lessons: 'lessons',
  quizzes: 'quizzes',
  caseStudies: 'case_studies',
  flashcards: 'flashcards',
  offlineActions: 'offline_actions',
  images: 'images',
} as const;

export type ContentType = 'lesson' | 'quiz' | 'case' | 'flashcard';

export interface OfflineAction {
  id?: number;
  type: 'quiz_result' | 'flashcard_review' | 'lesson_progress';
  payload: unknown;
  created_at: string;
  synced: boolean;
}

let dbPromise: Promise<IDBDatabase> | null = null;

function getDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') {
      reject(new Error('IndexedDB not available'));
      return;
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;

      if (!db.objectStoreNames.contains(STORES.lessons)) {
        db.createObjectStore(STORES.lessons, { keyPath: 'cache_key' });
      }
      if (!db.objectStoreNames.contains(STORES.quizzes)) {
        db.createObjectStore(STORES.quizzes, { keyPath: 'cache_key' });
      }
      if (!db.objectStoreNames.contains(STORES.caseStudies)) {
        db.createObjectStore(STORES.caseStudies, { keyPath: 'cache_key' });
      }
      if (!db.objectStoreNames.contains(STORES.flashcards)) {
        db.createObjectStore(STORES.flashcards, { keyPath: 'cache_key' });
      }
      if (!db.objectStoreNames.contains(STORES.offlineActions)) {
        const actionStore = db.createObjectStore(STORES.offlineActions, {
          keyPath: 'id',
          autoIncrement: true,
        });
        actionStore.createIndex('synced', 'synced', { unique: false });
      }
      if (!db.objectStoreNames.contains(STORES.images)) {
        db.createObjectStore(STORES.images, { keyPath: 'url' });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });

  return dbPromise;
}

function makeKey(
  moduleId: string,
  unitId: string,
  language: string,
  level: number,
  countryContext: string,
  contentType: ContentType
): string {
  return `${contentType}:${moduleId}:${unitId}:${language}:${level}:${countryContext}`;
}

function storeForType(contentType: ContentType): string {
  switch (contentType) {
    case 'lesson':
      return STORES.lessons;
    case 'quiz':
      return STORES.quizzes;
    case 'case':
      return STORES.caseStudies;
    case 'flashcard':
      return STORES.flashcards;
  }
}

export async function getContentFromDB<T>(
  moduleId: string,
  unitId: string,
  language: string,
  level: number,
  countryContext: string,
  contentType: ContentType
): Promise<T | null> {
  try {
    const db = await getDB();
    const key = makeKey(moduleId, unitId, language, level, countryContext, contentType);
    const store = storeForType(contentType);

    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const request = tx.objectStore(store).get(key);
      request.onsuccess = () => {
        const result = request.result;
        if (result) {
          resolve(result.data as T);
        } else {
          resolve(null);
        }
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

export async function saveContentToDB<T>(
  moduleId: string,
  unitId: string,
  language: string,
  level: number,
  countryContext: string,
  contentType: ContentType,
  data: T
): Promise<void> {
  try {
    const db = await getDB();
    const key = makeKey(moduleId, unitId, language, level, countryContext, contentType);
    const store = storeForType(contentType);

    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      const request = tx.objectStore(store).put({ cache_key: key, data, saved_at: new Date().toISOString() });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Silently fail — offline storage is best-effort
  }
}

export async function getFlashcardsFromDB(moduleId: string): Promise<unknown[] | null> {
  try {
    const db = await getDB();
    const key = `flashcard:${moduleId}`;

    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORES.flashcards, 'readonly');
      const request = tx.objectStore(STORES.flashcards).get(key);
      request.onsuccess = () => {
        const result = request.result;
        resolve(result ? (result.data as unknown[]) : null);
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

export async function saveFlashcardsToDB(moduleId: string, cards: unknown[]): Promise<void> {
  try {
    const db = await getDB();
    const key = `flashcard:${moduleId}`;

    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORES.flashcards, 'readwrite');
      const request = tx.objectStore(STORES.flashcards).put({
        cache_key: key,
        data: cards,
        saved_at: new Date().toISOString(),
      });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Silently fail
  }
}

export async function queueOfflineAction(action: Omit<OfflineAction, 'id' | 'synced'>): Promise<void> {
  try {
    const db = await getDB();

    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORES.offlineActions, 'readwrite');
      const request = tx.objectStore(STORES.offlineActions).add({
        ...action,
        synced: false,
      });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Silently fail
  }
}

export async function getPendingOfflineActions(): Promise<OfflineAction[]> {
  try {
    const db = await getDB();

    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORES.offlineActions, 'readonly');
      const store = tx.objectStore(STORES.offlineActions);
      const index = store.index('synced');
      const request = index.getAll(IDBKeyRange.only(false));
      request.onsuccess = () => resolve(request.result as OfflineAction[]);
      request.onerror = () => reject(request.error);
    });
  } catch {
    return [];
  }
}

export async function markActionSynced(id: number): Promise<void> {
  try {
    const db = await getDB();

    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORES.offlineActions, 'readwrite');
      const store = tx.objectStore(STORES.offlineActions);
      const getRequest = store.get(id);
      getRequest.onsuccess = () => {
        const record = getRequest.result;
        if (record) {
          record.synced = true;
          const putRequest = store.put(record);
          putRequest.onsuccess = () => resolve();
          putRequest.onerror = () => reject(putRequest.error);
        } else {
          resolve();
        }
      };
      getRequest.onerror = () => reject(getRequest.error);
    });
  } catch {
    // Silently fail
  }
}

export async function getImageFromDB(url: string): Promise<Blob | null> {
  try {
    const db = await getDB();

    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORES.images, 'readonly');
      const request = tx.objectStore(STORES.images).get(url);
      request.onsuccess = () => {
        const result = request.result;
        resolve(result ? (result.blob as Blob) : null);
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

export async function saveImageToDB(url: string, blob: Blob): Promise<void> {
  try {
    const db = await getDB();

    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORES.images, 'readwrite');
      const request = tx.objectStore(STORES.images).put({ url, blob, saved_at: new Date().toISOString() });
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
    // Silently fail
  }
}

export function isOnline(): boolean {
  if (typeof navigator === 'undefined') return true;
  return navigator.onLine;
}
