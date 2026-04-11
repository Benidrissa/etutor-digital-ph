'use client';

import { useTranslations } from 'next-intl';
import { CloudOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export function OfflineBadge() {
  const t = useTranslations('Offline');

  return (
    <Badge variant="secondary" className="bg-amber-100 text-amber-700 border-amber-200 gap-1">
      <CloudOff className="w-3 h-3" />
      {t('offlineBadge')}
    </Badge>
  );
}
