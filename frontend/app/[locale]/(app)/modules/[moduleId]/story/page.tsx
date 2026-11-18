import { getTranslations } from 'next-intl/server';
import { ChevronLeft } from 'lucide-react';

import { Link } from '@/i18n/routing';
import { EnrollmentGuard } from '@/components/shared/enrollment-guard';
import { ModuleStory } from '@/components/learning/module-story';

interface ModuleStoryPageProps {
  params: Promise<{ locale: string; moduleId: string }>;
}

export async function generateMetadata({ params }: ModuleStoryPageProps) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'ModuleStory' });
  return { title: t('pageTitle') };
}

/**
 * The module story: the whole module retold as one story, one chapter per
 * unit. The page itself fetches nothing, so it is quick to serve and opens
 * from the service worker's cache offline; the panel loads the story (from
 * IndexedDB when the module was downloaded). Only this route carries the
 * story player's code: the module page links here from a small card.
 */
export default async function ModuleStoryPage({ params }: ModuleStoryPageProps) {
  const { locale, moduleId } = await params;
  const language = locale === 'fr' ? 'fr' : 'en';
  const t = await getTranslations({ locale, namespace: 'ModuleStory' });

  return (
    <EnrollmentGuard moduleId={moduleId}>
      <div className="container mx-auto max-w-2xl px-4 py-6">
        <div className="mb-2">
          <Link
            href={`/modules/${moduleId}`}
            className="inline-flex min-h-11 items-center text-stone-600 transition-colors hover:text-stone-900"
          >
            <ChevronLeft className="mr-1 h-4 w-4" aria-hidden="true" />
            {t('backToModule')}
          </Link>
        </div>
        <ModuleStory moduleId={moduleId} language={language} />
      </div>
    </EnrollmentGuard>
  );
}
