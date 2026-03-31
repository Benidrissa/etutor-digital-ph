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
    <div className="flex h-[calc(100vh-theme(space.16))] md:h-[calc(100vh-theme(space.14))] flex-col">
      <div className="border-b bg-background p-4">
        <h1 className="text-2xl font-bold">{t('title')}</h1>
        <p className="text-muted-foreground">{t('tutorPageDescription')}</p>
      </div>
      <TutorPageClient />
    </div>
  );
}