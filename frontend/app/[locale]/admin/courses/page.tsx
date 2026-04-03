import { getTranslations } from 'next-intl/server';
import { AdminCoursesClient } from './admin-courses-client';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'AdminCourses' });
  return { title: t('title') };
}

export default async function AdminCoursesPage() {
  const t = await getTranslations('AdminCourses');

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-stone-900 mb-1">{t('title')}</h1>
        <p className="text-stone-600">{t('subtitle')}</p>
      </div>
      <AdminCoursesClient />
    </div>
  );
}
