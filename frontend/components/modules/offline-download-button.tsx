'use client';

import { useCallback, useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Download, Loader2, WifiOff } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { API_BASE } from '@/lib/api';
import {
  getOfflineModule,
  getModuleOfflinePercent,
  isModuleFullyOffline,
  OfflineBundleResponse,
} from '@/lib/offline/db';
import { OfflineDownloadDialog } from './offline-download-dialog';

interface Props {
  moduleId: string;
  moduleTitle: string;
}

type ButtonState = 'idle' | 'loading-bundle' | 'partial' | 'downloaded';

function getToken(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem('access_token') ?? '';
}

export function OfflineDownloadButton({ moduleId, moduleTitle }: Props) {
  const t = useTranslations('OfflineDownload');
  const [dialogOpen, setDialogOpen] = useState(false);
  const [buttonState, setButtonState] = useState<ButtonState>('idle');
  const [bundle, setBundle] = useState<OfflineBundleResponse | null>(null);
  const [pct, setPct] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const record = await getOfflineModule(moduleId);
      if (!record) {
        setButtonState('idle');
        return;
      }
      if (isModuleFullyOffline(record)) {
        setButtonState('downloaded');
      } else {
        setPct(getModuleOfflinePercent(record));
        setButtonState('partial');
      }
    } catch {
      setButtonState('idle');
    }
  }, [moduleId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleClick = useCallback(async () => {
    if (buttonState === 'idle' || buttonState === 'partial') {
      if (!bundle) {
        setButtonState('loading-bundle');
        try {
          const token = getToken();
          const res = await fetch(`${API_BASE}/api/v1/modules/${moduleId}/offline-bundle`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (!res.ok) throw new Error('fetch_failed');
          const data = (await res.json()) as OfflineBundleResponse;
          setBundle(data);
        } catch {
          setButtonState('idle');
          return;
        }
      }
      setDialogOpen(true);
    } else if (buttonState === 'downloaded') {
      setDialogOpen(true);
    }
  }, [buttonState, bundle, moduleId]);

  const handleStatusChange = useCallback(() => {
    refresh();
  }, [refresh]);

  if (buttonState === 'loading-bundle') {
    return (
      <Button variant="outline" disabled className="min-h-[44px] w-full">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {t('loading')}
      </Button>
    );
  }

  if (buttonState === 'downloaded') {
    return (
      <>
        <Button
          variant="outline"
          onClick={handleClick}
          className="min-h-[44px] w-full text-green-700"
          aria-label={t('availableOffline')}
        >
          <WifiOff className="mr-2 h-4 w-4" />
          {t('availableOffline')}
        </Button>
        <OfflineDownloadDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          moduleId={moduleId}
          moduleTitle={moduleTitle}
          totalSizeBytes={bundle?.total_size_bytes ?? 0}
          token={getToken()}
          onStatusChange={handleStatusChange}
        />
      </>
    );
  }

  if (buttonState === 'partial') {
    return (
      <>
        <Button
          variant="outline"
          onClick={handleClick}
          className="min-h-[44px] w-full"
          aria-label={t('resumeDownload', { pct })}
        >
          <Download className="mr-2 h-4 w-4" />
          {t('resumeDownload', { pct })}
        </Button>
        {bundle && (
          <OfflineDownloadDialog
            open={dialogOpen}
            onOpenChange={setDialogOpen}
            moduleId={moduleId}
            moduleTitle={moduleTitle}
            totalSizeBytes={bundle.total_size_bytes}
            token={getToken()}
            onStatusChange={handleStatusChange}
          />
        )}
      </>
    );
  }

  return (
    <>
      <Button
        variant="outline"
        onClick={handleClick}
        className="min-h-[44px] w-full"
        aria-label={t('download')}
      >
        <Download className="mr-2 h-4 w-4" />
        {t('download')}
      </Button>
      {bundle && (
        <OfflineDownloadDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          moduleId={moduleId}
          moduleTitle={moduleTitle}
          totalSizeBytes={bundle.total_size_bytes}
          token={getToken()}
          onStatusChange={handleStatusChange}
        />
      )}
    </>
  );
}
