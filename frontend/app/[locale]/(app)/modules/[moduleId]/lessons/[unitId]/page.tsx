import { getTranslations } from 'next-intl/server';
import { getLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';

import { getModuleById } from '@/lib/modules';
import { LessonViewer } from '@/components/learning/lesson-viewer';
import { CaseStudyViewer } from '@/components/learning/case-study-viewer';

interface LessonPageProps {
  params: Promise<{ moduleId: string; unitId: string }>;
}

export default async function LessonPage({ params }: LessonPageProps) {
  const { moduleId, unitId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('LessonPage');

  const moduleData = getModuleById(moduleId);
  const language = locale as 'fr' | 'en';
  const unit = moduleData?.units?.find(u => u.id === unitId);
  const moduleTitle = moduleData?.title[language] || moduleId;
  const unitTitle = unit?.title[language] || unitId;
  const moduleLevel = moduleData?.level || 1;
  const isCaseStudy = unit?.type === 'case-study' || unitId.toLowerCase().includes('u05');

  return (
    <div>
      {/* Breadcrumb */}
      <div className="container mx-auto max-w-4xl px-4 py-4 border-b">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Link
            href="/modules"
            className="hover:text-gray-900 transition-colors"
          >
            {t('modules')}
          </Link>
          <span>/</span>
          <Link
            href={`/modules/${moduleId}`}
            className="hover:text-gray-900 transition-colors"
          >
            {moduleTitle}
          </Link>
          <span>/</span>
          <span className="text-gray-900">
            {unitTitle}
          </span>
        </div>

        <Link
          href={`/modules/${moduleId}`}
          className="inline-flex items-center mt-2 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ChevronLeft className="w-4 h-4 mr-1" />
          {t('backToModule')}
        </Link>
      </div>

      {/* Lesson or Case Study Content */}
      {isCaseStudy ? (
        <CaseStudyViewer
          moduleId={moduleId}
          unitId={unitId}
          language={language}
          level={moduleLevel}
        />
      ) : (
        <LessonViewer
          moduleId={moduleId}
          unitId={unitId}
          language={language}
          level={moduleLevel}
        />
      )}
    </div>
  );
}

export async function generateMetadata({ params }: LessonPageProps) {
  const { moduleId, unitId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('LessonPage.metadata');

  const moduleData = getModuleById(moduleId);
  const language = locale as 'fr' | 'en';
  const unit = moduleData?.units?.find(u => u.id === unitId);

  return {
    title: t('title', {
      unit: unit?.title[language] || unitId,
      module: moduleData?.title[language] || moduleId
    }),
    description: unit?.description?.[language] || moduleData?.description?.[language] || '',
  };
}
