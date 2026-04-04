import { getTranslations } from 'next-intl/server';
import { ExpertCourseWizardClient } from '@/components/expert/course-wizard-client';

export async function generateMetadata() {
  const t = await getTranslations('ExpertCourses.wizard');
  return {
    title: t('title'),
  };
}

export default async function ExpertNewCoursePage() {
  return <ExpertCourseWizardClient />;
}
