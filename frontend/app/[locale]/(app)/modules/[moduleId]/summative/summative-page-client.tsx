'use client';

import { SummativeAssessmentContainer } from '@/components/quiz/summative-assessment-container';

interface SummativePageClientProps {
  moduleId: string;
  locale: string;
  language: string;
  country: string;
  level: number;
}

export function SummativePageClient({
  moduleId,
  locale,
  language,
  country,
  level,
}: SummativePageClientProps) {
  return (
    <main className="min-h-screen bg-stone-50">
      <div className="py-8">
        <SummativeAssessmentContainer
          moduleId={moduleId}
          language={language}
          country={country}
          level={level}
          onComplete={() => {
            window.location.href = `/${locale}/modules`;
          }}
          onRetry={() => {
            window.location.reload();
          }}
        />
      </div>
    </main>
  );
}
