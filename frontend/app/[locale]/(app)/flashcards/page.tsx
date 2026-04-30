import { Metadata } from 'next';
import { getTranslations } from 'next-intl/server';
import { FlashcardsContainer } from './flashcards-container';

export async function generateMetadata({ params }: { params: Promise<{ locale: string }> }): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: 'Flashcards' });
  
  return {
    title: t('title'),
    description: t('reviewDescription'),
  };
}

export default async function FlashcardsPage() {
  return <FlashcardsContainer />;
}