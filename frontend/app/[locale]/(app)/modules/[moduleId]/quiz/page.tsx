import { getTranslations, getLocale } from 'next-intl/server';
import { Link, redirect } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';
import { getModuleUnits } from '@/lib/api';
import { QuizPageClient } from './quiz-page-client';

interface QuizPageProps {
  params: Promise<{ moduleId: string }>;
  searchParams: Promise<{ unit?: string }>;
}

export default async function QuizPage({ params, searchParams }: QuizPageProps) {
  const { moduleId } = await params;
  const { unit } = await searchParams;
  const locale = await getLocale();

  // The summative assessment lives on its own page with the right submission
  // endpoint; the regular quiz page would record an inert quiz_attempts row
  // and never trigger certificate logic.
  if (unit === 'summative') {
    redirect({ href: `/modules/${moduleId}/summative`, locale });
  }

  const t = await getTranslations('QuizPage');

  const unitId = unit || 'unit-1';
  const language = locale as 'en' | 'fr';
  const moduleData = await getModuleUnits(moduleId).catch(() => null);
  const moduleTitle = language === 'fr' ? (moduleData?.title_fr || moduleId) : (moduleData?.title_en || moduleId);

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6">
        <Link
          href={`/modules/${moduleId}`}
          className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors"
        >
          <ChevronLeft className="w-4 h-4 mr-1" />
          {t('backToModule', { module: moduleTitle })}
        </Link>
      </div>

      <QuizPageClient
        moduleId={moduleId}
        unitId={unitId}
        language={language}
        level={moduleData?.level ?? 1}
      />
    </div>
  );
}
