/**
 * Offline-aware content loader.
 *
 * Each load function checks IndexedDB first when offline, falls back to the
 * API when online (and opportunistically caches the result). Components call
 * these instead of apiFetch directly.
 */

import { getOfflineContent, upsertOfflineContent, type ContentType } from './db';
import { apiFetch } from '@/lib/api';

export interface ContentLoadResult<T> {
  data: T;
  /** Where the data came from */
  source: 'api' | 'indexeddb';
}

/**
 * Generic content loader that checks IndexedDB when offline and API when online.
 * On API success, opportunistically caches the result in IndexedDB.
 */
async function loadContent<T>(
  unitId: string,
  contentType: ContentType,
  locale: 'fr' | 'en',
  moduleId: string,
  apiUrl: string,
  apiOptions?: RequestInit,
): Promise<ContentLoadResult<T>> {
  const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;

  // Offline: only check IndexedDB
  if (!isOnline) {
    const cached = await getOfflineContentWithFallback(moduleId, unitId, contentType, locale);
    if (cached) {
      return { data: cached.content as T, source: 'indexeddb' };
    }
    throw new OfflineContentNotAvailable(unitId, contentType);
  }

  // Online: try API first
  try {
    const data = await apiFetch<T>(apiUrl, apiOptions);

    // Opportunistically cache (fire-and-forget)
    upsertOfflineContent({
      unitId,
      moduleId,
      contentType,
      locale,
      content: data,
      cachedAt: Date.now(),
    }).catch(() => {/* IndexedDB write failure is non-fatal */});

    return { data, source: 'api' };
  } catch (err: unknown) {
    // On network error, fall back to IndexedDB
    if (isNetworkError(err)) {
      const cached = await getOfflineContentWithFallback(moduleId, unitId, contentType, locale);
      if (cached) {
        return { data: cached.content as T, source: 'indexeddb' };
      }
    }
    throw err;
  }
}

/**
 * Load a lesson, checking IndexedDB when offline.
 */
export function loadLesson<T>(
  moduleId: string,
  unitId: string,
  locale: 'fr' | 'en',
  level: number,
  country: string,
  forceRegenerate = false,
): Promise<ContentLoadResult<T>> {
  const forceParam = forceRegenerate ? '&force_regenerate=true' : '';
  return loadContent<T>(
    unitId, 'lesson', locale, moduleId,
    `/api/v1/content/lessons/${moduleId}/${unitId}?language=${locale}&level=${level}&country=${country}${forceParam}`,
  );
}

/**
 * Load a case study, checking IndexedDB when offline.
 */
export function loadCaseStudy<T>(
  moduleId: string,
  unitId: string,
  locale: 'fr' | 'en',
  level: number,
  country: string,
  forceRegenerate = false,
): Promise<ContentLoadResult<T>> {
  const forceParam = forceRegenerate ? '&force_regenerate=true' : '';
  return loadContent<T>(
    unitId, 'case_study', locale, moduleId,
    `/api/v1/content/cases/${moduleId}/${unitId}?language=${locale}&level=${level}&country=${country}${forceParam}`,
  );
}

/**
 * Load a quiz, checking IndexedDB when offline.
 * Note: quiz generation is a POST endpoint, so we handle it differently.
 */
export async function loadQuiz<T>(
  moduleId: string,
  unitId: string,
  locale: string,
  level: number,
  country: string,
  numQuestions: number,
  forceRegenerate = false,
): Promise<ContentLoadResult<T>> {
  const isOnline = typeof navigator !== 'undefined' ? navigator.onLine : true;
  const idbLocale = (locale === 'fr' || locale === 'en') ? locale : 'fr';

  // Offline: only check IndexedDB
  if (!isOnline) {
    const cached = await getOfflineContentWithFallback(moduleId, unitId, 'quiz', idbLocale);
    if (cached) {
      return { data: cached.content as T, source: 'indexeddb' };
    }
    throw new OfflineContentNotAvailable(unitId, 'quiz');
  }

  // Online: call the quiz generate endpoint (POST)
  try {
    const data = await apiFetch<T>('/api/v1/quiz/generate', {
      method: 'POST',
      body: JSON.stringify({
        module_id: moduleId,
        unit_id: unitId,
        language: locale,
        country,
        level,
        num_questions: numQuestions,
        force_regenerate: forceRegenerate,
      }),
    });

    // Opportunistically cache
    upsertOfflineContent({
      unitId,
      moduleId,
      contentType: 'quiz',
      locale: idbLocale,
      content: data,
      cachedAt: Date.now(),
    }).catch(() => {});

    return { data, source: 'api' };
  } catch (err: unknown) {
    if (isNetworkError(err)) {
      const cached = await getOfflineContentWithFallback(moduleId, unitId, 'quiz', idbLocale);
      if (cached) {
        return { data: cached.content as T, source: 'indexeddb' };
      }
    }
    throw err;
  }
}

/**
 * Load module flashcards, checking IndexedDB when offline.
 */
export async function loadFlashcards<T>(
  moduleId: string,
  locale: 'fr' | 'en',
  level: number,
): Promise<ContentLoadResult<T>> {
  const unitId = `__module_${moduleId}__`;
  return loadContent<T>(
    unitId, 'flashcard', locale, moduleId,
    `/api/v1/flashcards/modules/${moduleId}?language=${locale}&level=${level}`,
  );
}

// --- Error types ---

export class OfflineContentNotAvailable extends Error {
  unitId: string;
  contentType: ContentType;

  constructor(unitId: string, contentType: ContentType) {
    super(`Content not available offline: ${contentType} for ${unitId}`);
    this.name = 'OfflineContentNotAvailable';
    this.unitId = unitId;
    this.contentType = contentType;
  }
}

// --- Helpers ---

/**
 * Convert URL-format unitId ("M01-U05") to API-format ("1.5").
 * Returns null if the input doesn't match the MXX-UYY pattern.
 *
 * The download manager stores content under the API format (unit.unit_number),
 * but quiz/case-study pages pass the URL format from route params.
 */
function normalizeUnitId(unitId: string): string | null {
  const match = unitId.match(/^M0*(\d+)-U0*(\d+)$/);
  return match ? `${match[1]}.${match[2]}` : null;
}

/**
 * Look up offline content trying both the original unitId and the normalized
 * format (M01-U05 → 1.5) to handle the URL vs API format mismatch.
 */
async function getOfflineContentWithFallback(
  moduleId: string,
  unitId: string,
  contentType: ContentType,
  locale: 'fr' | 'en',
) {
  const cached = await getOfflineContent(moduleId, unitId, contentType, locale);
  if (cached) return cached;

  const normalized = normalizeUnitId(unitId);
  if (normalized && normalized !== unitId) {
    return getOfflineContent(moduleId, normalized, contentType, locale);
  }
  return undefined;
}

function isNetworkError(err: unknown): boolean {
  if (err instanceof TypeError && err.message.includes('fetch')) return true;
  if (err instanceof DOMException && err.name === 'AbortError') return false;
  if (err && typeof err === 'object' && 'status' in err) {
    // API errors (4xx, 5xx) are not network errors
    return false;
  }
  // Generic network failure
  return err instanceof Error && (
    err.message.includes('network') ||
    err.message.includes('Network') ||
    err.message.includes('Failed to fetch') ||
    err.message.includes('Load failed')
  );
}
