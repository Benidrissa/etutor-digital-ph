'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  downloadModule,
  cancelDownload,
  removeOfflineModule,
  canDownloadMore,
  estimateModuleSize,
  type DownloadProgress,
  type DownloadPhase,
} from '@/lib/offline/download-manager';
import {
  getOfflineModule,
  type OfflineModule,
  type ModuleDownloadStatus,
} from '@/lib/offline/db';

export interface UseDownloadManagerReturn {
  /** Current download status of this module */
  status: ModuleDownloadStatus;
  /** Download progress details when downloading */
  progress: DownloadProgress | null;
  /** Whether a download is currently active */
  isDownloading: boolean;
  /** Whether the module is fully available offline */
  isAvailableOffline: boolean;
  /** Whether user can download more modules (under 3 limit) */
  canDownload: boolean;
  /** Estimated size in bytes */
  estimatedSize: number;
  /** Number of downloaded units (for partial downloads) */
  downloadedUnits: number;
  /** Total units in the module */
  totalUnits: number;
  /** Error message if download failed */
  error: string | null;
  /** Start downloading the module */
  download: (options?: {
    wifiOnly?: boolean;
    level?: number;
    country?: string;
  }) => Promise<void>;
  /** Cancel an in-progress download */
  cancel: () => void;
  /** Remove the downloaded module and free space */
  remove: () => Promise<void>;
}

export function useDownloadManager(
  moduleId: string,
  locale: 'fr' | 'en',
  unitCount?: number
): UseDownloadManagerReturn {
  const [status, setStatus] = useState<ModuleDownloadStatus>('not_downloaded');
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [canDl, setCanDl] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadedUnits, setDownloadedUnits] = useState(0);
  const [totalUnits, setTotalUnits] = useState(unitCount ?? 0);

  // Load existing state from IndexedDB on mount
  useEffect(() => {
    let cancelled = false;

    async function loadState() {
      const mod = await getOfflineModule(moduleId);
      if (cancelled) return;

      if (mod) {
        setStatus(mod.status);
        setDownloadedUnits(mod.downloadedUnits);
        setTotalUnits(mod.totalUnits);
      } else {
        setStatus('not_downloaded');
      }

      setCanDl(await canDownloadMore());
    }

    loadState();
    return () => { cancelled = true; };
  }, [moduleId]);

  const download = useCallback(
    async (options?: { wifiOnly?: boolean; level?: number; country?: string }) => {
      setError(null);
      setStatus('downloading');

      try {
        await downloadModule(moduleId, locale, {
          ...options,
          onProgress: (p) => {
            setProgress(p);
            setDownloadedUnits(p.downloadedUnits);
            setTotalUnits(p.totalUnits);

            if (p.phase === 'complete') {
              setStatus('downloaded');
            } else if (p.phase === 'error') {
              setStatus('error');
              setError(p.error ?? 'Download failed');
            } else if (p.phase === 'cancelled') {
              // Keep current status (partial download is functional)
              getOfflineModule(moduleId).then((mod) => {
                if (mod) {
                  setStatus(mod.downloadedUnits > 0 ? mod.status : 'not_downloaded');
                } else {
                  setStatus('not_downloaded');
                }
              });
            }
          },
        });
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') return;
        setStatus('error');
        setError(err instanceof Error ? err.message : 'Download failed');
      }

      setCanDl(await canDownloadMore());
    },
    [moduleId, locale]
  );

  const cancel = useCallback(() => {
    cancelDownload(moduleId);
  }, [moduleId]);

  const remove = useCallback(async () => {
    await removeOfflineModule(moduleId);
    setStatus('not_downloaded');
    setProgress(null);
    setDownloadedUnits(0);
    setError(null);
    setCanDl(await canDownloadMore());
  }, [moduleId]);

  return {
    status,
    progress,
    isDownloading: status === 'downloading',
    isAvailableOffline: status === 'downloaded',
    canDownload: canDl || status === 'downloaded',
    estimatedSize: estimateModuleSize(unitCount ?? totalUnits),
    downloadedUnits,
    totalUnits,
    error,
    download,
    cancel,
    remove,
  };
}
