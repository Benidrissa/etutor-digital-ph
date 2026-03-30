'use client';

import { useRouter } from 'next/navigation';
import { ModuleMap } from '@/components/learning/module-map';

export function DashboardClient() {
  const router = useRouter();

  const handleModuleClick = (moduleId: string) => {
    // Navigate to module overview page
    router.push(`/modules/${moduleId}`);
  };

  return <ModuleMap onModuleClick={handleModuleClick} />;
}