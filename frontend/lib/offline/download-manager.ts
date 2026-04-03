'use client';

import { API_BASE } from '@/lib/api';
import {
  OfflineBundleResponse,
  OfflineModuleRecord,
  deleteOfflineModule,
  getAllOfflineModules,
  getOfflineModule,
  saveOfflineModule,
  updateUnitStatus,
} from './db';

export const MAX_OFFLINE_MODULES = 3;

export type DownloadProgressCallback = (moduleId: string, unitId: string, done: number, total: number) => void;

export interface DownloadOptions {
  wifiOnly?: boolean;
  onProgress?: DownloadProgressCallback;
  signal?: AbortSignal;
}

function isOnWifi(): boolean {
  if (typeof navigator === 'undefined') return true;
  const conn = (navigator as unknown as { connection?: { type?: string } }).connection;
  if (!conn) return true;
  return conn.type === 'wifi' || conn.type === 'ethernet';
}

async function fetchBundle(moduleId: string, token: string): Promise<OfflineBundleResponse> {
  const res = await fetch(`${API_BASE}/api/v1/modules/${moduleId}/offline-bundle`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 404) throw new Error('module_not_found');
  if (!res.ok) throw new Error('bundle_fetch_failed');
  return res.json() as Promise<OfflineBundleResponse>;
}

export async function getOfflineModuleCount(): Promise<number> {
  const all = await getAllOfflineModules();
  return all.length;
}

export async function startModuleDownload(
  moduleId: string,
  token: string,
  options: DownloadOptions = {},
): Promise<void> {
  const { wifiOnly = false, onProgress, signal } = options;

  if (wifiOnly && !isOnWifi()) {
    throw new Error('wifi_required');
  }

  const existing = await getAllOfflineModules();
  const alreadyDownloaded = existing.find((m) => m.module_id === moduleId);

  if (!alreadyDownloaded) {
    const count = existing.length;
    if (count >= MAX_OFFLINE_MODULES) {
      throw new Error('max_modules_reached');
    }
  }

  const bundle = await fetchBundle(moduleId, token);

  const existing_record = await getOfflineModule(moduleId);
  const record: OfflineModuleRecord = existing_record ?? {
    module_id: bundle.module_id,
    module_number: bundle.module_number,
    title_fr: bundle.title_fr,
    title_en: bundle.title_en,
    total_size_bytes: bundle.total_size_bytes,
    downloaded_at: Date.now(),
    units: bundle.units.map((u) => ({
      ...u,
      download_status: 'pending',
      downloaded_bytes: 0,
    })),
  };

  if (!existing_record) {
    await saveOfflineModule(record);
  }

  const pendingUnits = record.units.filter((u) => u.download_status !== 'done');

  for (let i = 0; i < pendingUnits.length; i++) {
    if (signal?.aborted) break;

    const unit = pendingUnits[i];

    await updateUnitStatus(bundle.module_id, unit.unit_id, 'downloading', 0);

    try {
      const contentFetches: Promise<void>[] = [];

      if (unit.content_ids.lesson) {
        contentFetches.push(
          fetch(`${API_BASE}/api/v1/content/${unit.content_ids.lesson}`, {
            headers: { Authorization: `Bearer ${token}` },
            signal,
          }).then(() => {}),
        );
      }
      if (unit.content_ids.quiz) {
        contentFetches.push(
          fetch(`${API_BASE}/api/v1/content/${unit.content_ids.quiz}`, {
            headers: { Authorization: `Bearer ${token}` },
            signal,
          }).then(() => {}),
        );
      }
      for (const url of unit.image_urls) {
        contentFetches.push(
          fetch(url, { signal }).then(() => {}),
        );
      }

      await Promise.allSettled(contentFetches);

      await updateUnitStatus(bundle.module_id, unit.unit_id, 'done', unit.size_bytes);

      onProgress?.(bundle.module_id, unit.unit_id, i + 1, pendingUnits.length);
    } catch {
      if (signal?.aborted) break;
      await updateUnitStatus(bundle.module_id, unit.unit_id, 'error');
    }
  }
}

export async function removeModuleDownload(moduleId: string): Promise<void> {
  await deleteOfflineModule(moduleId);
}
