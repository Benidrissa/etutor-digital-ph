const DB_NAME = 'santePubliqueOffline';
const DB_VERSION = 1;

export type ContentType = 'lessons' | 'quizzes' | 'case_studies' | 'flashcards';

export interface OfflineAction {
  id?: number;
  type: 'quiz_result' | 'flashcard_review' | 'lesson_progress' | 'case_study_complete';
  payload: Record<string, unknown>;
  created_at: number;
  synced: boolean;
}

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result;

      const stores: ContentType[] = ['lessons', 'quizzes', 'case_studies', 'flashcards'];
      for (const store of stores) {
        if (!db.objectStoreNames.contains(store)) {
          db.createObjectStore(store, { keyPath: 'id' });
        }
      }

      if (!db.objectStoreNames.contains('offline_actions')) {
        const actionsStore = db.createObjectStore('offline_actions', {
          keyPath: 'id',
          autoIncrement: true,
        });
        actionsStore.createIndex('synced', 'synced', { unique: false });
      }

      if (!db.objectStoreNames.contains('images')) {
        db.createObjectStore('images', { keyPath: 'id' });
      }
    };

    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export function isOnline(): boolean {
  if (typeof navigator === 'undefined') return true;
  return navigator.onLine;
}

export async function getContentFromDB<T>(
  store: ContentType,
  id: string
): Promise<T | null> {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(store, 'readonly');
      const request = tx.objectStore(store).get(id);
      request.onsuccess = () => resolve((request.result as T) ?? null);
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

export async function saveContentToDB<T extends { id: string }>(
  store: ContentType,
  data: T
): Promise<void> {
  try {
    const db = await openDB();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(store, 'readwrite');
      const request = tx.objectStore(store).put(data);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
  }
}

export async function queueOfflineAction(action: Omit<OfflineAction, 'id' | 'created_at' | 'synced'>): Promise<void> {
  try {
    const db = await openDB();
    const record: Omit<OfflineAction, 'id'> = {
      ...action,
      created_at: Date.now(),
      synced: false,
    };
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('offline_actions', 'readwrite');
      const request = tx.objectStore('offline_actions').add(record);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  } catch {
  }
}

export async function getImageFromDB(id: string): Promise<Blob | null> {
  try {
    const db = await openDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('images', 'readonly');
      const request = tx.objectStore('images').get(id);
      request.onsuccess = () => {
        const result = request.result as { id: string; blob: Blob } | undefined;
        resolve(result?.blob ?? null);
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}
