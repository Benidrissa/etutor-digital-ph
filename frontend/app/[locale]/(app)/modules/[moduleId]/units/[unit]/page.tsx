import { notFound } from 'next/navigation';
import { getLocale, getTranslations } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';

import { getModuleUnits } from '@/lib/api';
import { EnrollmentGuard } from '@/components/shared/enrollment-guard';
import { LessonViewer } from '@/components/learning/lesson-viewer';
import { CaseStudyViewer } from '@/components/learning/case-study-viewer';
import { UnitQuizViewer } from '@/components/learning/unit-quiz-viewer';

interface UnitPageProps {
  params: Promise<{ moduleId: string; unit: string }>;
}

export default async function UnitPage({ params }: UnitPageProps) {
  const { moduleId, unit: unitParam } = await params;
  const locale = await getLocale();
  const language = locale as 'fr' | 'en';
  const t = await getTranslations('UnitPage');

  const moduleData = await getModuleUnits(moduleId).catch(() => null);
  if (!moduleData) notFound();

  const unit = moduleData.units?.find(
    (u) => u.unit_number === unitParam || u.id === unitParam,
  );
  if (!unit) notFound();

  const moduleTitle = language === 'fr' ? moduleData.title_fr : moduleData.title_en;
  const unitTitle = language === 'fr' ? unit.title_fr : unit.title_en;
  const unitDescription = language === 'fr' ? unit.description_fr : unit.description_en;
  const learningObjectives =
    language === 'fr' ? moduleData.learning_objectives_fr : moduleData.learning_objectives_en;
  const level = moduleData.level ?? 1;

  const containerWidth =
    unit.unit_type === 'quiz' ? 'max-w-6xl' : 'max-w-4xl';

  return (
    <EnrollmentGuard moduleId={moduleId}>
      <div className={`container mx-auto ${containerWidth} px-4 py-6`}>
        <div className="mb-4">
          <Link
            href={`/modules/${moduleId}`}
            className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors"
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            {t('backToModule', { module: moduleTitle })}
          </Link>
        </div>

        {unit.unit_type === 'quiz' ? (
          <UnitQuizViewer
            moduleId={moduleId}
            unitId={unit.unit_number}
            language={language}
            level={level}
          />
        ) : unit.unit_type === 'scenario' || unit.unit_type === 'case-study' ? (
          <CaseStudyViewer
            moduleId={moduleId}
            unitId={unit.unit_number}
            language={language}
            level={level}
            unitTitle={unitTitle}
            unitDescription={unitDescription}
            learningObjectives={learningObjectives}
            bloomLevel={moduleData.bloom_level}
            estimatedMinutes={unit.estimated_minutes}
          />
        ) : (
          <LessonViewer
            moduleId={moduleId}
            unitId={unit.unit_number}
            language={language}
            level={level}
            estimatedMinutes={unit.estimated_minutes}
          />
        )}
      </div>
    </EnrollmentGuard>
  );
}

export async function generateMetadata({ params }: UnitPageProps) {
  const { moduleId, unit: unitParam } = await params;
  const locale = await getLocale();
  const language = locale as 'fr' | 'en';

  const moduleData = await getModuleUnits(moduleId).catch(() => null);
  const unit = moduleData?.units?.find(
    (u) => u.unit_number === unitParam || u.id === unitParam,
  );

  const modTitle = language === 'fr' ? moduleData?.title_fr : moduleData?.title_en;
  const unitTitle = language === 'fr' ? unit?.title_fr : unit?.title_en;

  return {
    title: [unitTitle, modTitle].filter(Boolean).join(' · '),
    description:
      (language === 'fr' ? unit?.description_fr : unit?.description_en) ||
      (language === 'fr' ? moduleData?.description_fr : moduleData?.description_en) ||
      '',
  };
}
