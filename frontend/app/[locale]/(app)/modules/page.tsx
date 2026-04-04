'use client';

import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import { useSearchParams } from 'next/navigation';
import { ModuleMap } from '@/components/learning/module-map';

export default function ModulesPage() {
  const t = useTranslations('ModuleMap');
  const router = useRouter();
  const searchParams = useSearchParams();
  const courseId = searchParams.get('course_id') ?? undefined;

  const handleModuleClick = (moduleId: string) => {
    router.push(`/modules/${moduleId}`);
  };

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-bold text-stone-900 mb-2">
          {t('title')}
        </h1>
        <p className="text-stone-600 text-lg">
          {t('subtitle')}
        </p>
      </div>

      <ModuleMap onModuleClick={handleModuleClick} courseId={courseId} />
    </div>
  );
}