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
    <div className="flex flex-1 min-h-0 flex-col overflow-hidden h-[calc(100dvh-8rem)]">
      <div className="border-b bg-background p-4 shrink-0">
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        <p className="text-muted-foreground">{t('tutorPageDescription')}</p>
      </div>
      <TutorPageClient />
    </div>
  );
}