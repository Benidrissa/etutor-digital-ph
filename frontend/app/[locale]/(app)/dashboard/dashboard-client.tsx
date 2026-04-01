'use client';

import { useRouter } from 'next/navigation';
import { useLocale } from 'next-intl';
import { ModuleMap } from '@/components/learning/module-map';

export function DashboardClient() {
  const router = useRouter();
  const locale = useLocale();

  const handleModuleClick = (moduleId: string) => {
    router.push(`/${locale}/modules/${moduleId}`);
  };

  return <ModuleMap onModuleClick={handleModuleClick} />;
}