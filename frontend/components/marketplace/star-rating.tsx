import { useTranslations } from 'next-intl';
import { Star } from 'lucide-react';
import { cn } from '@/lib/utils';

interface StarRatingProps {
  rating: number;
  reviewCount?: number;
  className?: string;
  showCount?: boolean;
}

export function StarRating({
  rating,
  reviewCount,
  className,
  showCount = true,
}: StarRatingProps) {
  const t = useTranslations('Marketplace');
  const clampedRating = Math.min(5, Math.max(0, rating));
  const fullStars = Math.floor(clampedRating);
  const hasHalf = clampedRating % 1 >= 0.5;

  return (
    <div
      className={cn('flex items-center gap-1', className)}
      aria-label={t('rating', { rating: clampedRating.toFixed(1) })}
      role="img"
    >
      <div className="flex items-center" aria-hidden="true">
        {Array.from({ length: 5 }, (_, i) => {
          const filled = i < fullStars;
          const half = !filled && i === fullStars && hasHalf;
          return (
            <Star
              key={i}
              className={cn(
                'h-3.5 w-3.5',
                filled || half
                  ? 'fill-amber-400 text-amber-400'
                  : 'fill-stone-200 text-stone-200'
              )}
            />
          );
        })}
      </div>
      <span className="text-xs font-medium text-stone-700">
        {clampedRating.toFixed(1)}
      </span>
      {showCount && reviewCount !== undefined && (
        <span className="text-xs text-stone-500">
          ({t('reviews', { count: reviewCount })})
        </span>
      )}
    </div>
  );
}
