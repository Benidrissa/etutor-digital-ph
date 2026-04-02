import { getTranslations } from 'next-intl/server';
import { CourseCatalogClient } from './courses-client';

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'Courses' });
  return { title: t('catalogTitle') };
}

export default async function CoursesPage() {
  const t = await getTranslations('Courses');

  return (
    <div className="container mx-auto max-w-6xl px-4 py-6">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-stone-900 mb-1">{t('catalogTitle')}</h1>
        <p className="text-stone-600">{t('catalogSubtitle')}</p>
      </div>
      <CourseCatalogClient />
    </div>
  );
}
