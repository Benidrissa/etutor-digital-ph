'use client';

import {
  deleteOfflineModule,
  getAllOfflineModules,
  getOfflineModule,
  saveOfflineModule,
  updateUnitStatus,
  type OfflineModule,
  type OfflineUnit,
} from './db';
import { API_BASE } from '@/lib/api';

export const MAX_OFFLINE_MODULES = 3;

export interface OfflineBundleManifest {
  module_id: string;
  module_number: number;
  title_fr: string;
  title_en: string;
  description_fr?: string;
  description_en?: string;
  estimated_hours: number;
  level: number;
  units: {
    unit_id: string;
    unit_number: string;
    title_fr: string;
    title_en: string;
    description_fr?: string;
    description_en?: string;
    estimated_minutes: number;
    order_index: number;
    lesson_content_id: string | null;
    quiz_content_id: string | null;
    case_study_content_id: string | null;
  }[];
  estimated_size_bytes: number;
  cached_content_count: number;
}

export type DownloadProgressCallback = (moduleId: string, unitId: string, done: boolean) => void;

const abortControllers: Map<string, AbortController> = new Map();

export async function fetchOfflineManifest(
  moduleId: string,
  token: string
): Promise<OfflineBundleManifest> {
  const res = await fetch(`${API_BASE}/api/v1/modules/${moduleId}/offline-bundle`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch offline manifest: ${res.status}`);
  }
  return res.json() as Promise<OfflineBundleManifest>;
}

export async function getDownloadedModuleCount(): Promise<number> {
  const all = await getAllOfflineModules();
  return all.filter((m) => m.units.some((u) => u.status === 'downloaded')).length;
}

export async function canDownloadMore(): Promise<boolean> {
  const count = await getDownloadedModuleCount();
  return count < MAX_OFFLINE_MODULES;
}

export function isWifiOnly(): boolean {
  if (typeof navigator === 'undefined') return false;
  const conn = (navigator as Navigator & { connection?: { type?: string; effectiveType?: string } })
    .connection;
  if (!conn) return false;
  return conn.type === 'cellular';
}

async function fetchContentById(
  contentId: string,
  token: string,
  signal: AbortSignal
): Promise<unknown> {
  const endpoints = [
    `/api/v1/content/lessons/${contentId}`,
    `/api/v1/content/quizzes/${contentId}`,
    `/api/v1/content/case-studies/${contentId}`,
  ];
  for (const endpoint of endpoints) {
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal,
      });
      if (res.ok) return res.json();
    } catch {
      // try next endpoint
    }
  }
  return null;
}

export async function downloadModule(
  moduleId: string,
  manifest: OfflineBundleManifest,
  token: string,
  wifiOnly: boolean,
  onProgress: DownloadProgressCallback
): Promise<void> {
  if (wifiOnly && isWifiOnly()) {
    throw new Error('wifi_only_blocked');
  }

  const existing = await getOfflineModule(manifest.module_id);
  const units: OfflineUnit[] = manifest.units.map((u) => {
    const prev = existing?.units.find((eu) => eu.unitId === u.unit_id);
    return {
      unitId: u.unit_id,
      unitNumber: u.unit_number,
      titleFr: u.title_fr,
      titleEn: u.title_en,
      estimatedMinutes: u.estimated_minutes,
      orderIndex: u.order_index,
      status: prev?.status === 'downloaded' ? 'downloaded' : 'not_downloaded',
      lessonContentId: u.lesson_content_id,
      quizContentId: u.quiz_content_id,
      caseStudyContentId: u.case_study_content_id,
      lessonData: prev?.lessonData ?? null,
      quizData: prev?.quizData ?? null,
      caseStudyData: prev?.caseStudyData ?? null,
      downloadedAt: prev?.downloadedAt ?? null,
    };
  });

  const offlineModule: OfflineModule = {
    moduleId: manifest.module_id,
    moduleNumber: manifest.module_number,
    titleFr: manifest.title_fr,
    titleEn: manifest.title_en,
    level: manifest.level,
    estimatedHours: manifest.estimated_hours,
    estimatedSizeBytes: manifest.estimated_size_bytes,
    units,
    downloadedAt: existing?.downloadedAt ?? null,
    lastUpdated: Date.now(),
  };

  await saveOfflineModule(offlineModule);

  const controller = new AbortController();
  abortControllers.set(manifest.module_id, controller);

  try {
    for (const unit of units) {
      if (controller.signal.aborted) break;
      if (unit.status === 'downloaded') {
        onProgress(manifest.module_id, unit.unitId, true);
        continue;
      }

      await updateUnitStatus(manifest.module_id, unit.unitId, { status: 'downloading' });

      try {
        let lessonData: unknown = null;
        let quizData: unknown = null;
        let caseStudyData: unknown = null;

        if (unit.lessonContentId) {
          lessonData = await fetchContentById(unit.lessonContentId, token, controller.signal);
        }
        if (!controller.signal.aborted && unit.quizContentId) {
          quizData = await fetchContentById(unit.quizContentId, token, controller.signal);
        }
        if (!controller.signal.aborted && unit.caseStudyContentId) {
          caseStudyData = await fetchContentById(
            unit.caseStudyContentId,
            token,
            controller.signal
          );
        }

        if (controller.signal.aborted) break;

        await updateUnitStatus(manifest.module_id, unit.unitId, {
          status: 'downloaded',
          lessonData,
          quizData,
          caseStudyData,
          downloadedAt: Date.now(),
        });

        onProgress(manifest.module_id, unit.unitId, true);
      } catch (err) {
        if ((err as Error).name === 'AbortError') break;
        await updateUnitStatus(manifest.module_id, unit.unitId, { status: 'error' });
        onProgress(manifest.module_id, unit.unitId, false);
      }
    }

    const updated = await getOfflineModule(manifest.module_id);
    if (updated && updated.units.every((u) => u.status === 'downloaded')) {
      await saveOfflineModule({ ...updated, downloadedAt: Date.now() });
    }
  } finally {
    abortControllers.delete(manifest.module_id);
  }
}

export function pauseDownload(moduleId: string): void {
  abortControllers.get(moduleId)?.abort();
  abortControllers.delete(moduleId);
}

export async function removeOfflineModule(moduleId: string): Promise<void> {
  pauseDownload(moduleId);
  await deleteOfflineModule(moduleId);
}
