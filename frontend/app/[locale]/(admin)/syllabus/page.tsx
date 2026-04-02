import { getTranslations } from 'next-intl/server';
import { SyllabusPageClient } from './syllabus-client';

export async function generateMetadata() {
  const t = await getTranslations('AdminSyllabus');
  return {
    title: t('pageTitle'),
    description: t('pageDescription'),
  };
}

export default async function SyllabusPage() {
  const t = await getTranslations('AdminSyllabus');
  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t('pageTitle')}</h1>
        <p className="text-muted-foreground mt-1">{t('pageDescription')}</p>
      </div>
      <SyllabusPageClient />
    </div>
  );
}
