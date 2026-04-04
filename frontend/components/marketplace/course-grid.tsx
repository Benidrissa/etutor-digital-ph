import { useTranslations } from 'next-intl';
import { ShoppingBag } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { type MarketplaceCourse } from '@/lib/api';
import { MarketplaceCard } from './marketplace-card';

interface CourseGridProps {
  courses: MarketplaceCourse[];
  loading: boolean;
  error: boolean;
  locale: string;
  hasActiveFilters: boolean;
  onRetry: () => void;
  onClearFilters: () => void;
}

export function CourseGrid({
  courses,
  loading,
  error,
  locale,
  hasActiveFilters,
  onRetry,
  onClearFilters,
}: CourseGridProps) {
  const t = useTranslations('Marketplace');

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-stone-500 text-sm">{t('loading')}</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-4">
        <p className="text-red-500 text-sm">{t('error')}</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          {t('tryAgain')}
        </Button>
      </div>
    );
  }

  if (courses.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-4 text-center">
        <div className="rounded-full bg-teal-50 p-6">
          <ShoppingBag className="h-12 w-12 text-teal-600" aria-hidden="true" />
        </div>
        <h2 className="text-lg font-semibold text-stone-900">{t('noResults')}</h2>
        <p className="text-stone-500 text-sm max-w-sm">{t('noResultsDescription')}</p>
        {hasActiveFilters && (
          <button
            type="button"
            onClick={onClearFilters}
            className="text-teal-600 hover:underline font-medium text-sm"
          >
            {t('clearFilters')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {courses.map((course) => (
        <MarketplaceCard key={course.id} course={course} locale={locale} />
      ))}
    </div>
  );
}
