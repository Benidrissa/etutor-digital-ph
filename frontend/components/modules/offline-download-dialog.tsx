'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Progress, ProgressTrack, ProgressIndicator } from '@/components/ui/progress';
import {
  MAX_OFFLINE_MODULES,
  removeModuleDownload,
  startModuleDownload,
} from '@/lib/offline/download-manager';
import {
  OfflineModuleRecord,
  getAllOfflineModules,
  getOfflineModule,
  getModuleOfflinePercent,
  isModuleFullyOffline,
} from '@/lib/offline/db';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  moduleId: string;
  moduleTitle: string;
  totalSizeBytes: number;
  token: string;
  onStatusChange?: () => void;
}

type DialogState =
  | 'confirm'
  | 'limit-reached'
  | 'downloading'
  | 'done'
  | 'remove-confirm'
  | 'error';

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function OfflineDownloadDialog({
  open,
  onOpenChange,
  moduleId,
  moduleTitle,
  totalSizeBytes,
  token,
  onStatusChange,
}: Props) {
  const t = useTranslations('OfflineDownload');
  const [dialogState, setDialogState] = useState<DialogState>('confirm');
  const [wifiOnly, setWifiOnly] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentUnitId, setCurrentUnitId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [existingRecord, setExistingRecord] = useState<OfflineModuleRecord | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;

    async function checkExisting() {
      try {
        const record = await getOfflineModule(moduleId);
        if (cancelled) return;

        if (record) {
          setExistingRecord(record);
          if (isModuleFullyOffline(record)) {
            setDialogState('remove-confirm');
          } else {
            const pct = getModuleOfflinePercent(record);
            setProgress(pct);
            setDialogState('confirm');
          }
          return;
        }

        const all = await getAllOfflineModules();
        if (cancelled) return;

        if (all.length >= MAX_OFFLINE_MODULES) {
          setDialogState('limit-reached');
        } else {
          setDialogState('confirm');
        }
      } catch {
      }
    }

    checkExisting();
    return () => {
      cancelled = true;
    };
  }, [open, moduleId]);

  const handleDownload = useCallback(async () => {
    setDialogState('downloading');
    setProgress(0);
    setError(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await startModuleDownload(moduleId, token, {
        wifiOnly,
        signal: controller.signal,
        onProgress: (_mid, unitId, done, total) => {
          setCurrentUnitId(unitId);
          setProgress(Math.round((done / total) * 100));
        },
      });

      if (!controller.signal.aborted) {
        setDialogState('done');
        onStatusChange?.();
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg = err instanceof Error ? err.message : 'unknown';
      if (msg === 'wifi_required') {
        setError(t('errorWifiRequired'));
      } else if (msg === 'max_modules_reached') {
        setDialogState('limit-reached');
        return;
      } else {
        setError(t('errorDownloadFailed'));
      }
      setDialogState('error');
    }
  }, [moduleId, token, wifiOnly, t, onStatusChange]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
    onOpenChange(false);
  }, [onOpenChange]);

  const handleRemove = useCallback(async () => {
    try {
      await removeModuleDownload(moduleId);
      onStatusChange?.();
      onOpenChange(false);
    } catch {
    }
  }, [moduleId, onStatusChange, onOpenChange]);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        {dialogState === 'confirm' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('confirmTitle')}</AlertDialogTitle>
              <AlertDialogDescription>
                {t('confirmDesc', { title: moduleTitle, size: formatBytes(totalSizeBytes) })}
              </AlertDialogDescription>
            </AlertDialogHeader>

            <div className="flex items-center gap-2 py-2">
              <input
                id="wifi-only"
                type="checkbox"
                checked={wifiOnly}
                onChange={(e) => setWifiOnly(e.target.checked)}
                className="h-5 w-5 rounded border border-input accent-primary"
              />
              <label htmlFor="wifi-only" className="text-sm">
                {t('wifiOnly')}
              </label>
            </div>

            {existingRecord && getModuleOfflinePercent(existingRecord) > 0 && (
              <p className="text-xs text-muted-foreground">
                {t('resumeInfo', { pct: getModuleOfflinePercent(existingRecord) })}
              </p>
            )}

            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => onOpenChange(false)}>
                {t('cancel')}
              </AlertDialogCancel>
              <Button onClick={handleDownload} className="min-h-[44px]">
                {t('download')}
              </Button>
            </AlertDialogFooter>
          </>
        )}

        {dialogState === 'limit-reached' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('limitTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{t('limitDesc', { max: MAX_OFFLINE_MODULES })}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => onOpenChange(false)}>
                {t('close')}
              </AlertDialogCancel>
            </AlertDialogFooter>
          </>
        )}

        {dialogState === 'downloading' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('downloadingTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{t('downloadingDesc')}</AlertDialogDescription>
            </AlertDialogHeader>

            <div className="space-y-2 py-2">
              <Progress value={progress}>
                <ProgressTrack>
                  <ProgressIndicator />
                </ProgressTrack>
              </Progress>
              <p className="text-xs text-muted-foreground">{progress}%</p>
              {currentUnitId && (
                <p className="truncate text-xs text-muted-foreground">{currentUnitId}</p>
              )}
            </div>

            <AlertDialogFooter>
              <Button variant="outline" onClick={handleCancel} className="min-h-[44px]">
                {t('cancel')}
              </Button>
            </AlertDialogFooter>
          </>
        )}

        {dialogState === 'done' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('doneTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{t('doneDesc', { title: moduleTitle })}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <Button onClick={() => onOpenChange(false)} className="min-h-[44px]">
                {t('close')}
              </Button>
            </AlertDialogFooter>
          </>
        )}

        {dialogState === 'remove-confirm' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('removeTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{t('removeDesc', { title: moduleTitle })}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => onOpenChange(false)}>
                {t('cancel')}
              </AlertDialogCancel>
              <Button variant="destructive" onClick={handleRemove} className="min-h-[44px]">
                {t('remove')}
              </Button>
            </AlertDialogFooter>
          </>
        )}

        {dialogState === 'error' && (
          <>
            <AlertDialogHeader>
              <AlertDialogTitle>{t('errorTitle')}</AlertDialogTitle>
              <AlertDialogDescription>{error}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel onClick={() => onOpenChange(false)}>
                {t('close')}
              </AlertDialogCancel>
              <Button onClick={() => setDialogState('confirm')} className="min-h-[44px]">
                {t('retry')}
              </Button>
            </AlertDialogFooter>
          </>
        )}
      </AlertDialogContent>
    </AlertDialog>
  );
}
