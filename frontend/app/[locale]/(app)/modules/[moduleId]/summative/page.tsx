import { getTranslations } from 'next-intl/server';
import { SummativePageClient } from './summative-page-client';

interface SummativePageProps {
  params: Promise<{
    locale: string;
    moduleId: string;
  }>;
}

export async function generateMetadata({ params }: SummativePageProps) {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'SummativeAssessment' });

  return {
    title: t('pageTitle'),
    description: t('pageDescription'),
  };
}

export default async function SummativePage({ params }: SummativePageProps) {
  const { locale, moduleId } = await params;
  const language = locale === 'fr' ? 'fr' : 'en';

  return (
    <SummativePageClient
      moduleId={moduleId}
      locale={locale}
      language={language}
      country="senegal"
      level={1}
    />
  );
}
