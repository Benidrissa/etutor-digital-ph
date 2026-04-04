import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';

interface PriceBadgeProps {
  isFree: boolean;
  credits?: number;
  className?: string;
}

export function PriceBadge({ isFree, credits = 0, className }: PriceBadgeProps) {
  const t = useTranslations('Marketplace');

  if (isFree) {
    return (
      <span
        className={cn(
          'inline-flex items-center rounded-full bg-teal-50 px-2.5 py-0.5 text-xs font-semibold text-teal-700 border border-teal-200',
          className
        )}
      >
        {t('free')}
      </span>
    );
  }

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full bg-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-700 border border-amber-200',
        className
      )}
    >
      {t('credits', { count: credits })}
    </span>
  );
}
