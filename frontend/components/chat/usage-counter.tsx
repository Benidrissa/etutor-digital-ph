'use client';

import { useTranslations } from 'next-intl';
import { AlertTriangle } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface UsageCounterProps {
  currentUsage: number;
  maxUsage: number;
  className?: string;
}

export function UsageCounter({ currentUsage, maxUsage, className }: UsageCounterProps) {
  const t = useTranslations('ChatTutor');
  const usagePercentage = (currentUsage / maxUsage) * 100;
  const isWarning = usagePercentage >= 80;
  const isLimitReached = currentUsage >= maxUsage;
  const remaining = Math.max(0, maxUsage - currentUsage);

  const getVariant = () => {
    if (isLimitReached) return 'destructive';
    if (isWarning) return 'default';
    return 'secondary';
  };

  return (
    <div className={cn('space-y-2', className)}>
      {/* Counter Badge */}
      <div className="flex justify-center">
        <Badge variant={getVariant()} className="px-3 py-1">
          {t('messageLimit', { remaining, max: maxUsage })}
        </Badge>
      </div>

      {/* Warning Alert */}
      {isWarning && !isLimitReached && (
        <Alert className="border-yellow-200 bg-yellow-50 text-yellow-800">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t('messageLimitWarning')}</AlertTitle>
          <AlertDescription>
            {t('messageLimitWarningDescription')}
          </AlertDescription>
        </Alert>
      )}

      {/* Limit Reached Alert */}
      {isLimitReached && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{t('messageLimitReached')}</AlertTitle>
          <AlertDescription>
            {t('messageLimitReachedDescription')}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}