'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Download, Loader2, Lock, WifiOff } from 'lucide-react';

import {
  getOfflineModule,
  type OfflineModule,
  type UnitDownloadStatus,
} from '@/lib/offline/db';

interface UnitOfflineStatusProps {
  moduleId: string;
  unitId: string;
}

function getStatusIcon(status: UnitDownloadStatus | undefined) {
  switch (status) {
    case 'downloaded':
      return <WifiOff className="w-4 h-4 text-teal-600" aria-hidden="true" />;
    case 'downloading':
      return <Loader2 className="w-4 h-4 text-stone-400 animate-spin" aria-hidden="true" />;
    case 'error':
      return <Lock className="w-4 h-4 text-red-400" aria-hidden="true" />;
    case 'not_downloaded':
      return <Download className="w-4 h-4 text-stone-300" aria-hidden="true" />;
    default:
      return null;
  }
}

export function UnitOfflineStatus({ moduleId, unitId }: UnitOfflineStatusProps) {
  const t = useTranslations('OfflineDownload');
  const [offlineModule, setOfflineModule] = useState<OfflineModule | null>(null);

  useEffect(() => {
    getOfflineModule(moduleId).then(setOfflineModule).catch(() => setOfflineModule(null));
  }, [moduleId]);

  const unit = offlineModule?.units.find((u) => u.unitId === unitId);
  if (!unit || !offlineModule) return null;

  const ariaLabel = {
    downloaded: t('unitStatusAvailable'),
    downloading: t('unitStatusDownloading'),
    error: t('unitStatusError'),
    not_downloaded: t('unitStatusNotDownloaded'),
  }[unit.status];

  return (
    <span aria-label={ariaLabel} title={ariaLabel}>
      {getStatusIcon(unit.status)}
    </span>
  );
}

interface ModuleOfflineBadgeProps {
  moduleId: string;
}

export function ModuleOfflineBadge({ moduleId }: ModuleOfflineBadgeProps) {
  const t = useTranslations('OfflineDownload');
  const [offlineModule, setOfflineModule] = useState<OfflineModule | null>(null);

  useEffect(() => {
    getOfflineModule(moduleId).then(setOfflineModule).catch(() => setOfflineModule(null));
  }, [moduleId]);

  if (!offlineModule) return null;

  const downloaded = offlineModule.units.filter((u) => u.status === 'downloaded').length;
  const total = offlineModule.units.length;

  if (downloaded === 0) return null;

  const isComplete = downloaded === total;

  return (
    <span
      className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${
        isComplete
          ? 'bg-teal-100 text-teal-700'
          : 'bg-stone-100 text-stone-600'
      }`}
      aria-label={
        isComplete
          ? t('badgeAvailable')
          : t('badgePartial', { percent: Math.round((downloaded / total) * 100) })
      }
    >
      {isComplete ? (
        <CheckCircle className="w-3 h-3" aria-hidden="true" />
      ) : (
        <Download className="w-3 h-3" aria-hidden="true" />
      )}
      {isComplete
        ? t('badgeAvailable')
        : t('badgePartial', { percent: Math.round((downloaded / total) * 100) })}
    </span>
  );
}
