'use client';

import { useRouter } from '@/i18n/routing';
import { ModuleMap } from '@/components/learning/module-map';

export function DashboardClient() {
  const router = useRouter();

  const handleModuleClick = (moduleId: string) => {
    router.push(`/modules/${moduleId}`);
  };

  return <ModuleMap onModuleClick={handleModuleClick} />;
}