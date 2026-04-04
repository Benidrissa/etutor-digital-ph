import { getTranslations } from 'next-intl/server';
import { getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';

import { API_BASE, ModuleUnitsResponse } from '@/lib/api';
import { LessonViewer } from '@/components/learning/lesson-viewer';
import { CaseStudyViewer } from '@/components/learning/case-study-viewer';

interface LessonPageProps {
  params: Promise<{ moduleId: string; unitId: string }>;
}

async function fetchModuleData(moduleId: string): Promise<ModuleUnitsResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/content/modules/${moduleId}/units`, {
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

export default async function LessonPage({ params }: LessonPageProps) {
  const { moduleId, unitId } = await params;
  const locale = await getLocale();
  const t = await getTranslations('LessonPage');

  const language = locale as 'fr' | 'en';
  const moduleData = await fetchModuleData(moduleId);
  const unit = moduleData?.units?.find(u => u.unit_number === unitId || u.id === unitId);
  const moduleTitle = language === 'fr' ? (moduleData?.title_fr || moduleId) : (moduleData?.title_en || moduleId);
  const unitTitle = language === 'fr' ? (unit?.title_fr || unitId) : (unit?.title_en || unitId);
  const moduleLevel = moduleData?.level || 1;
  const isCaseStudy = unitId.toLowerCase().includes('u05');

  return (
    <div>
      {/* Breadcrumb */}
      <div className="container mx-auto max-w-4xl px-4 py-4 border-b">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Link
            href="/dashboard"
            className="hover:text-gray-900 transition-colors"
          >
            {t('dashboard')}
          </Link>
          <span>/</span>
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

  const language = locale as 'fr' | 'en';
  const moduleData = await fetchModuleData(moduleId);
  const unit = moduleData?.units?.find(u => u.unit_number === unitId || u.id === unitId);
  const unitTitle = language === 'fr' ? (unit?.title_fr || unitId) : (unit?.title_en || unitId);
  const modTitle = language === 'fr' ? (moduleData?.title_fr || moduleId) : (moduleData?.title_en || moduleId);

  return {
    title: t('title', { unit: unitTitle, module: modTitle }),
    description: language === 'fr' ? (unit?.description_fr || moduleData?.description_fr || '') : (unit?.description_en || moduleData?.description_en || ''),
  };
}
