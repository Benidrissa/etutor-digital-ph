import { getTranslations } from 'next-intl/server';
import { TutorPageClient } from './tutor-client';

export async function generateMetadata() {
  const t = await getTranslations('ChatTutor');
  
  return {
    title: t('title'),
    description: t('tutorPageDescription'),
  };
}

export default async function TutorPage() {
  const t = await getTranslations('ChatTutor');
  
  return (
    <div className="fixed inset-0 top-14 bottom-16 md:left-64 md:bottom-0 flex flex-col overflow-hidden bg-background z-10">
      <div className="border-b bg-background p-3 shrink-0">
        <h1 className="text-lg font-bold">{t('title')}</h1>
      </div>
      <TutorPageClient />
    </div>
  );
}