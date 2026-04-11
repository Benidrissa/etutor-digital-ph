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
  return (
    <div className="fixed inset-0 top-0 bottom-16 md:left-64 md:bottom-0 flex flex-col overflow-hidden bg-background z-10">
      <TutorPageClient />
    </div>
  );
}