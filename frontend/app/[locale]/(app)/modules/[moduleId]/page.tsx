import { getLocale } from 'next-intl/server';

import { ModuleLockGate } from '@/components/learning/module-lock-gate';

interface ModuleOverviewPageProps {
  params: Promise<{ moduleId: string }>;
}

export default async function ModuleOverviewPage({ params }: ModuleOverviewPageProps) {
  const { moduleId } = await params;
  const locale = await getLocale();
  const language = locale as 'en' | 'fr';

  return (
    <ModuleLockGate
      moduleId={moduleId}
      language={language}
    />
  );
}
