'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Download, Wifi, WifiOff, AlertTriangle, CheckCircle, Loader2, Trash2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import {
  canDownloadMore,
  downloadModule,
  fetchOfflineManifest,
  MAX_OFFLINE_MODULES,
  pauseDownload,
  removeOfflineModule,
  type OfflineBundleManifest,
} from '@/lib/offline/download-manager';
import {
  getModuleDownloadPercent,
  getOfflineModule,
  isModuleFullyDownloaded,
  type OfflineModule,
} from '@/lib/offline/db';

interface OfflineDownloadDialogProps {
  moduleId: string;
  moduleTitleFr: string;
  moduleTitleEn: string;
  locale: 'fr' | 'en';
  token: string;
}

type DialogState =
  | 'idle'
  | 'fetching_manifest'
  | 'confirm'
  | 'at_limit'
  | 'downloading'
  | 'completed'
  | 'removing';

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function OfflineDownloadDialog({
  moduleId,
  moduleTitleFr,
  moduleTitleEn,
  locale,
  token,
}: OfflineDownloadDialogProps) {
  const t = useTranslations('OfflineDownload');

  const [open, setOpen] = useState(false);
  const [dialogState, setDialogState] = useState<DialogState>('idle');
  const [manifest, setManifest] = useState<OfflineBundleManifest | null>(null);
  const [offlineModule, setOfflineModule] = useState<OfflineModule | null>(null);
  const [wifiOnly, setWifiOnly] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [completedUnits, setCompletedUnits] = useState(0);
  const [totalUnits, setTotalUnits] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false);

  const moduleTitle = locale === 'fr' ? moduleTitleFr : moduleTitleEn;

  const refreshOfflineState = useCallback(async () => {
    const mod = await getOfflineModule(moduleId);
    setOfflineModule(mod);
    if (mod) {
      setDownloadProgress(getModuleDownloadPercent(mod));
      setCompletedUnits(mod.units.filter((u) => u.status === 'downloaded').length);
      setTotalUnits(mod.units.length);
    }
  }, [moduleId]);

  useEffect(() => {
    let cancelled = false;
    getOfflineModule(moduleId).then((mod) => {
      if (cancelled) return;
      setOfflineModule(mod);
      if (mod) {
        setDownloadProgress(getModuleDownloadPercent(mod));
        setCompletedUnits(mod.units.filter((u) => u.status === 'downloaded').length);
        setTotalUnits(mod.units.length);
      }
    });
    return () => { cancelled = true; };
  }, [moduleId]);

  const handleOpenDialog = async () => {
    setError(null);
    const mod = await getOfflineModule(moduleId);
    setOfflineModule(mod);

    if (mod && isModuleFullyDownloaded(mod)) {
      setOpen(true);
      setDialogState('completed');
      return;
    }

    if (mod && mod.units.some((u) => u.status === 'downloaded' || u.status === 'downloading')) {
      setOpen(true);
      setDialogState('downloading');
      return;
    }

    const canDownload = await canDownloadMore();
    if (!canDownload) {
      setOpen(true);
      setDialogState('at_limit');
      return;
    }

    setDialogState('fetching_manifest');
    setOpen(true);

    try {
      const m = await fetchOfflineManifest(moduleId, token);
      setManifest(m);
      setTotalUnits(m.units.length);
      setDialogState('confirm');
    } catch {
      setError(t('errorFetchManifest'));
      setDialogState('idle');
      setOpen(false);
    }
  };

  const handleStartDownload = async () => {
    if (!manifest) return;
    setDialogState('downloading');
    setCompletedUnits(0);
    setDownloadProgress(0);

    try {
      await downloadModule(
        moduleId,
        manifest,
        token,
        wifiOnly,
        async (_modId, _unitId, done) => {
          if (done) {
            setCompletedUnits((prev) => {
              const next = prev + 1;
              setDownloadProgress(Math.round((next / (manifest?.units.length ?? 1)) * 100));
              return next;
            });
          }
          await refreshOfflineState();
        }
      );
      await refreshOfflineState();
      setDialogState('completed');
    } catch (err) {
      const msg = (err as Error).message;
      if (msg === 'wifi_only_blocked') {
        setError(t('errorWifiOnly'));
      } else {
        setError(t('errorDownload'));
      }
      setDialogState('confirm');
    }
  };

  const handlePause = () => {
    pauseDownload(moduleId);
    setDialogState('confirm');
  };

  const handleRemove = async () => {
    setDialogState('removing');
    await removeOfflineModule(moduleId);
    setOfflineModule(null);
    setDownloadProgress(0);
    setCompletedUnits(0);
    setShowRemoveConfirm(false);
    setOpen(false);
    setDialogState('idle');
  };

  const isDownloaded = offlineModule && isModuleFullyDownloaded(offlineModule);
  const isPartiallyDownloaded =
    offlineModule &&
    !isDownloaded &&
    offlineModule.units.some((u) => u.status === 'downloaded');
  const downloadPercent = offlineModule ? getModuleDownloadPercent(offlineModule) : 0;

  const getBadgeLabel = () => {
    if (isDownloaded) return t('badgeAvailable');
    if (isPartiallyDownloaded) return t('badgePartial', { percent: downloadPercent });
    return null;
  };

  const badgeLabel = getBadgeLabel();

  return (
    <>
      <div className="flex items-center gap-2">
        {badgeLabel && (
          <Badge
            variant={isDownloaded ? 'default' : 'secondary'}
            className="text-xs"
            aria-label={badgeLabel}
          >
            {isDownloaded ? (
              <CheckCircle className="w-3 h-3 mr-1" aria-hidden="true" />
            ) : (
              <Download className="w-3 h-3 mr-1" aria-hidden="true" />
            )}
            {badgeLabel}
          </Badge>
        )}

        <Button
          variant="outline"
          size="sm"
          className="min-h-11 min-w-11"
          onClick={handleOpenDialog}
          aria-label={isDownloaded ? t('removeButtonAriaLabel') : t('downloadButtonAriaLabel')}
        >
          {isDownloaded ? (
            <>
              <Trash2 className="w-4 h-4 mr-2" aria-hidden="true" />
              {t('removeButton')}
            </>
          ) : (
            <>
              <Download className="w-4 h-4 mr-2" aria-hidden="true" />
              {isPartiallyDownloaded
                ? t('resumeButton')
                : t('downloadButton')}
            </>
          )}
        </Button>
      </div>

      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent className="max-w-sm mx-4">
          {dialogState === 'fetching_manifest' && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
                  {t('fetchingTitle')}
                </AlertDialogTitle>
                <AlertDialogDescription>{t('fetchingDescription')}</AlertDialogDescription>
              </AlertDialogHeader>
            </>
          )}

          {dialogState === 'confirm' && manifest && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle>{t('confirmTitle')}</AlertDialogTitle>
                <AlertDialogDescription className="sr-only">
                  {t('confirmTitle')}
                </AlertDialogDescription>
                <div className="space-y-3 text-sm text-stone-600">
                    <p>
                      {t('confirmDescription', { module: moduleTitle })}
                    </p>
                    <p className="font-medium text-stone-800">
                      {t('estimatedSize', { size: formatBytes(manifest.estimated_size_bytes) })}
                    </p>
                    <p>{t('unitCount', { count: manifest.units.length })}</p>

                    <div className="flex items-center gap-2 pt-1">
                      <button
                        type="button"
                        role="switch"
                        aria-checked={wifiOnly}
                        onClick={() => setWifiOnly((v) => !v)}
                        className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal-600 ${
                          wifiOnly ? 'bg-teal-600' : 'bg-stone-300'
                        }`}
                        aria-label={t('wifiOnlyToggleAriaLabel')}
                      >
                        <span
                          className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                            wifiOnly ? 'translate-x-6' : 'translate-x-1'
                          }`}
                        />
                      </button>
                      <span className="flex items-center gap-1 text-stone-700">
                        {wifiOnly ? (
                          <Wifi className="w-4 h-4 text-teal-600" aria-hidden="true" />
                        ) : (
                          <WifiOff className="w-4 h-4 text-stone-400" aria-hidden="true" />
                        )}
                        {t('wifiOnly')}
                      </span>
                    </div>

                    {error && (
                      <p className="flex items-center gap-1 text-red-600">
                        <AlertTriangle className="w-4 h-4" aria-hidden="true" />
                        {error}
                      </p>
                    )}
                  </div>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="min-h-11">{t('cancel')}</AlertDialogCancel>
                <AlertDialogAction
                  className="min-h-11 bg-teal-600 hover:bg-teal-700"
                  onClick={handleStartDownload}
                >
                  {t('startDownload')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}

          {dialogState === 'at_limit' && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-500" aria-hidden="true" />
                  {t('atLimitTitle')}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t('atLimitDescription', { max: MAX_OFFLINE_MODULES })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="min-h-11">{t('cancel')}</AlertDialogCancel>
              </AlertDialogFooter>
            </>
          )}

          {dialogState === 'downloading' && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin text-teal-600" aria-hidden="true" />
                  {t('downloadingTitle')}
                </AlertDialogTitle>
                <AlertDialogDescription className="sr-only">
                  {t('downloadingTitle')}
                </AlertDialogDescription>
                <div className="space-y-3 text-sm text-stone-600">
                    <p>
                      {t('downloadingUnits', {
                        completed: completedUnits,
                        total: totalUnits,
                      })}
                    </p>
                    <Progress
                      value={downloadProgress}
                      className="h-2"
                      aria-label={t('progressAriaLabel', { percent: downloadProgress })}
                    />
                    <p className="text-right text-xs text-stone-500">{downloadProgress}%</p>
                  </div>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel className="min-h-11" onClick={handlePause}>
                  {t('pauseDownload')}
                </AlertDialogCancel>
              </AlertDialogFooter>
            </>
          )}

          {dialogState === 'completed' && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <CheckCircle className="w-5 h-5 text-green-600" aria-hidden="true" />
                  {t('completedTitle')}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t('completedDescription', { module: moduleTitle })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter className="flex-col gap-2 sm:flex-row">
                <Button
                  variant="outline"
                  size="sm"
                  className="min-h-11 text-red-600 border-red-200 hover:bg-red-50"
                  onClick={() => setShowRemoveConfirm(true)}
                >
                  <Trash2 className="w-4 h-4 mr-2" aria-hidden="true" />
                  {t('removeDownload')}
                </Button>
                <AlertDialogAction
                  className="min-h-11"
                  onClick={() => setOpen(false)}
                >
                  {t('close')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </>
          )}

          {dialogState === 'removing' && (
            <>
              <AlertDialogHeader>
                <AlertDialogTitle className="flex items-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin" aria-hidden="true" />
                  {t('removingTitle')}
                </AlertDialogTitle>
              </AlertDialogHeader>
            </>
          )}
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog open={showRemoveConfirm} onOpenChange={setShowRemoveConfirm}>
        <AlertDialogContent className="max-w-sm mx-4">
          <AlertDialogHeader>
            <AlertDialogTitle>{t('removeConfirmTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('removeConfirmDescription', { module: moduleTitle })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="min-h-11">{t('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="min-h-11 bg-red-600 hover:bg-red-700"
              onClick={handleRemove}
            >
              {t('confirmRemove')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
