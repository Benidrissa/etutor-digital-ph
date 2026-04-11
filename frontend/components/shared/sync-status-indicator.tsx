'use client';

import { useTranslations } from 'next-intl';
import { RefreshCw, CheckCircle, AlertTriangle, CloudUpload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useSyncStatus } from '@/lib/hooks/use-sync-status';

export function SyncStatusIndicator() {
  const t = useTranslations('Offline');
  const { status, pendingCount, isSyncing, syncNow } = useSyncStatus();

  // Nothing to show when idle with no pending items
  if (status.state === 'idle' && pendingCount === 0) return null;

  // Syncing
  if (isSyncing) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center justify-center gap-2 bg-blue-50 border-b border-blue-100 px-4 py-1.5 text-xs font-medium text-blue-700"
      >
        <RefreshCw className="h-3.5 w-3.5 animate-spin shrink-0" aria-hidden="true" />
        <span>{t('syncing')}</span>
        {status.state === 'syncing' && (
          <span className="text-blue-500">
            {status.current}/{status.total}
          </span>
        )}
      </div>
    );
  }

  // Sync complete
  if (status.state === 'complete') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center justify-center gap-2 bg-teal-50 border-b border-teal-100 px-4 py-1.5 text-xs font-medium text-teal-700"
      >
        <CheckCircle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{t('syncSuccess', { count: status.synced })}</span>
      </div>
    );
  }

  // Sync error
  if (status.state === 'error') {
    return (
      <div
        role="alert"
        className="flex items-center justify-center gap-2 bg-red-50 border-b border-red-100 px-4 py-1.5 text-xs font-medium text-red-700"
      >
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{t('syncFailed')}</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={syncNow}
          className="h-6 px-2 text-xs text-red-700 hover:bg-red-100"
        >
          {t('syncRetry')}
        </Button>
      </div>
    );
  }

  // Idle with pending items
  if (pendingCount > 0) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center justify-center gap-2 bg-amber-50 border-b border-amber-100 px-4 py-1.5 text-xs font-medium text-amber-700"
      >
        <CloudUpload className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>{t('syncPending', { count: pendingCount })}</span>
      </div>
    );
  }

  return null;
}
