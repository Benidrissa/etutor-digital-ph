import { getTranslations } from 'next-intl/server';
import { ExpertCoursesClient } from '@/components/expert/courses-client';

export async function generateMetadata() {
  const t = await getTranslations('ExpertCourses');
  return {
    title: t('pageTitle'),
    description: t('pageDescription'),
  };
}

export default async function ExpertCoursesPage() {
  const t = await getTranslations('ExpertCourses');
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t('pageTitle')}</h1>
        <p className="text-muted-foreground mt-1">{t('pageDescription')}</p>
      </div>
      <ExpertCoursesClient />
    </div>
  );
}
