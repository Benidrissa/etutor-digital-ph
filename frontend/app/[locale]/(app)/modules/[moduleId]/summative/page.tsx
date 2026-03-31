import { getTranslations } from 'next-intl/server';
import { SummativeAssessmentContainer } from '@/components/quiz/summative-assessment-container';

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
  
  // Mock user data - in production this would come from auth
  const mockUser = {
    language: locale === 'fr' ? 'fr' : 'en',
    country: 'senegal',
    level: 1,
  };
  
  return (
    <main className="min-h-screen bg-stone-50">
      <div className="py-8">
        <SummativeAssessmentContainer
          moduleId={moduleId}
          language={mockUser.language}
          country={mockUser.country}
          level={mockUser.level}
          onComplete={() => {
            // Handle completion - redirect to next module or dashboard
            window.location.href = `/${locale}/modules`;
          }}
          onRetry={() => {
            // Handle retry - refresh the page or re-initialize
            window.location.reload();
          }}
        />
      </div>
    </main>
  );
}