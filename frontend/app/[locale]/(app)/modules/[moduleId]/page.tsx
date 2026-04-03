import { notFound } from 'next/navigation';

import { getModuleById, getPrerequisiteModules } from '@/lib/modules';
import { ModuleLockGate } from '@/components/learning/module-lock-gate';

interface ModuleOverviewPageProps {
  params: Promise<{ moduleId: string }>;
}

export default async function ModuleOverviewPage({ params }: ModuleOverviewPageProps) {
  const { moduleId } = await params;

  const moduleData = getModuleById(moduleId);

  if (!moduleData) {
    notFound();
  }

  const prerequisites = getPrerequisiteModules(moduleData);

  return (
    <ModuleLockGate
      moduleId={moduleId}
      moduleData={moduleData}
      prerequisites={prerequisites}
    />
  );
}
