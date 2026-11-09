'use client';

import { useTranslations } from 'next-intl';

/**
 * Placeholder for the module story page while the story loads: a title, the
 * chapter index and the first lines of a chapter.
 */
export function ModuleStorySkeleton() {
  const t = useTranslations('ModuleStory');
  return (
    <div aria-busy="true" className="mx-auto max-w-2xl">
      <p className="sr-only" role="status">
        {t('loading')}
      </p>
      <div className="h-4 w-1/3 animate-pulse rounded bg-gray-200" />
      <div className="mt-2 h-7 w-2/3 animate-pulse rounded bg-gray-200" />
      <div className="mt-6 h-11 animate-pulse rounded-lg bg-gray-200" />
      <div className="mt-6 space-y-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="h-14 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    </div>
  );
}
