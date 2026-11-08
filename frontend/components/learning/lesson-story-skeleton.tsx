'use client';

import { useTranslations } from 'next-intl';

/**
 * Placeholder for the lesson's Story tab: shown while the story player's code
 * downloads (it is split out of the lesson page) and while the story itself
 * loads. Kept in its own small file so the lesson page can show it without
 * pulling in the player.
 */
export function LessonStorySkeleton() {
  const t = useTranslations('LessonStory');
  return (
    <div aria-busy="true" className="mx-auto max-w-2xl">
      <p className="sr-only" role="status">
        {t('loading')}
      </p>
      <div className="h-6 w-2/3 animate-pulse rounded bg-gray-200" />
      <div className="mt-4 space-y-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="h-14 animate-pulse rounded-lg bg-gray-200" />
        ))}
      </div>
    </div>
  );
}
