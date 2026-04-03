import { getLocale } from 'next-intl/server';
import { notFound } from 'next/navigation';

import { getModuleById, getPrerequisiteModules } from '@/lib/modules';
import { ModuleLockGate } from '@/components/learning/module-lock-gate';

interface ModuleOverviewPageProps {
  params: Promise<{ moduleId: string }>;
}

export default async function ModuleOverviewPage({ params }: ModuleOverviewPageProps) {
  const { moduleId } = await params;
  const locale = await getLocale();

  const moduleData = getModuleById(moduleId);

  if (!moduleData) {
    notFound();
  }

  const prerequisites = getPrerequisiteModules(moduleData);
  const language = locale as 'en' | 'fr';

  return (
    <ModuleLockGate
      moduleId={moduleId}
      moduleData={moduleData}
      prerequisites={prerequisites}
      language={language}
    />
  );
}
