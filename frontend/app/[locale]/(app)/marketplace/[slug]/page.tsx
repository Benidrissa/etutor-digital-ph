import { getTranslations } from 'next-intl/server';
import { getCourseBySlug } from '@/lib/api';
import { CourseDetail } from '@/components/marketplace/course-detail';

interface PageProps {
  params: Promise<{ locale: string; slug: string }>;
}

export async function generateMetadata({ params }: PageProps) {
  const { locale, slug } = await params;
  try {
    const course = await getCourseBySlug(slug);
    const title = locale === 'fr' ? course.title_fr : course.title_en;
    return { title };
  } catch {
    const t = await getTranslations({ locale, namespace: 'Marketplace' });
    return { title: t('notFound') };
  }
}

export default async function MarketplaceCourseDetailPage({ params }: PageProps) {
  const { locale, slug } = await params;
  const t = await getTranslations({ locale, namespace: 'Marketplace' });

  let course;
  try {
    course = await getCourseBySlug(slug);
  } catch {
    return (
      <div className="container mx-auto max-w-3xl px-4 py-16 flex flex-col items-center gap-4 text-center">
        <p className="text-stone-500 text-sm">{t('error')}</p>
      </div>
    );
  }

  return <CourseDetail course={course} />;
}
