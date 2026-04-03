'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { CheckCircle, Loader2, Lock } from 'lucide-react';

import { UnitDownloadStatus, getModuleOfflinePercent, isModuleFullyOffline } from '@/lib/offline/db';
import { Badge } from '@/components/ui/badge';

interface UnitOfflineStatusProps {
  moduleId: string;
  unitId: string;
}

export function UnitOfflineStatus({ moduleId, unitId }: UnitOfflineStatusProps) {
  const [status, setStatus] = useState<UnitDownloadStatus | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const { getOfflineModule } = await import('@/lib/offline/db');
        const record = await getOfflineModule(moduleId);
        if (cancelled) return;
        if (!record) return;
        const unit = record.units.find((u) => u.unit_id === unitId);
        if (unit) setStatus(unit.download_status);
      } catch {
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, [moduleId, unitId]);

  if (!status || status === 'pending') return null;

  if (status === 'downloading') {
    return <Loader2 className="h-4 w-4 animate-spin text-primary" aria-label="Downloading" />;
  }

  if (status === 'done') {
    return <CheckCircle className="h-4 w-4 text-green-600" aria-label="Available offline" />;
  }

  if (status === 'error') {
    return <Lock className="h-4 w-4 text-muted-foreground" aria-label="Download error" />;
  }

  return null;
}

interface ModuleOfflineBadgeProps {
  moduleId: string;
}

export function ModuleOfflineBadge({ moduleId }: ModuleOfflineBadgeProps) {
  const t = useTranslations('OfflineDownload');
  const [badgeInfo, setBadgeInfo] = useState<{
    variant: 'default' | 'secondary' | 'outline';
    label: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const { getOfflineModule } = await import('@/lib/offline/db');
        const record = await getOfflineModule(moduleId);
        if (cancelled) return;

        if (!record) {
          return;
        }

        if (isModuleFullyOffline(record)) {
          setBadgeInfo({ variant: 'default', label: t('badgeAvailable') });
        } else {
          const pct = getModuleOfflinePercent(record);
          setBadgeInfo({ variant: 'secondary', label: t('badgePartial', { pct }) });
        }
      } catch {
      }
    }

    check();
    return () => {
      cancelled = true;
    };
  }, [moduleId, t]);

  if (!badgeInfo) return null;

  return <Badge variant={badgeInfo.variant}>{badgeInfo.label}</Badge>;
}
