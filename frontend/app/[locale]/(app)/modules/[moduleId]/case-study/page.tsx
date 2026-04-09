import { getTranslations, getLocale } from 'next-intl/server';
import { Link } from '@/i18n/routing';
import { ChevronLeft } from 'lucide-react';
import { getModuleUnits } from '@/lib/api';
import { CaseStudyViewer } from '@/components/learning/case-study-viewer';
import { EnrollmentGuard } from '@/components/shared/enrollment-guard';
import { CURRICULUM_MODULES } from '@/lib/modules';

interface CaseStudyPageProps {
  params: Promise<{ moduleId: string }>;
  searchParams: Promise<{ unit?: string }>;
}

export default async function CaseStudyPage({ params, searchParams }: CaseStudyPageProps) {
  const { moduleId } = await params;
  const { unit } = await searchParams;
  const locale = await getLocale();
  const t = await getTranslations('CaseStudyPage');

  const unitId = unit || '';
  const language = locale as 'en' | 'fr';
  const moduleData = await getModuleUnits(moduleId).catch(() => null);
  const moduleTitle = language === 'fr' ? (moduleData?.title_fr || moduleId) : (moduleData?.title_en || moduleId);

  const staticModule = CURRICULUM_MODULES.find((m) => m.id === moduleId);
  const learningObjectives = staticModule?.learningObjectives?.[language];

  const matchedUnit = moduleData?.units?.find((u) => u.id === unitId);
  const unitDescription = matchedUnit
    ? (language === 'fr' ? matchedUnit.description_fr : matchedUnit.description_en)
    : undefined;
  const estimatedMinutes = matchedUnit?.estimated_minutes ?? undefined;

  return (
    <EnrollmentGuard moduleId={moduleId}>
      <div className="container mx-auto max-w-4xl px-4 py-6">
        <div className="mb-6">
          <Link
            href={`/modules/${moduleId}`}
            className="inline-flex items-center text-stone-600 hover:text-stone-900 transition-colors"
          >
            <ChevronLeft className="w-4 h-4 mr-1" />
            {t('backToModule', { module: moduleTitle })}
          </Link>
        </div>

        <CaseStudyViewer
          moduleId={moduleId}
          unitId={unitId}
          language={language}
          level={moduleData?.level ?? 1}
          unitDescription={unitDescription}
          learningObjectives={learningObjectives}
          estimatedMinutes={estimatedMinutes}
        />
      </div>
    </EnrollmentGuard>
  );
}

export async function generateMetadata({ params, searchParams }: CaseStudyPageProps) {
  const { moduleId } = await params;
  const { unit } = await searchParams;
  const locale = await getLocale();
  const t = await getTranslations('CaseStudyPage.metadata');

  const language = locale as 'fr' | 'en';
  const moduleData = await getModuleUnits(moduleId).catch(() => null);
  const modTitle = language === 'fr' ? (moduleData?.title_fr || moduleId) : (moduleData?.title_en || moduleId);

  return {
    title: t('title', { unit: unit || '', module: modTitle }),
  };
}
