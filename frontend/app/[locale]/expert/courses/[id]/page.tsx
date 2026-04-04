import { getTranslations } from 'next-intl/server';
import { ExpertCourseDetailClient } from '@/components/expert/course-detail-client';

export async function generateMetadata() {
  const t = await getTranslations('ExpertCourses');
  return {
    title: t('pageTitle'),
  };
}

export default async function ExpertCourseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ExpertCourseDetailClient courseId={id} />;
}
