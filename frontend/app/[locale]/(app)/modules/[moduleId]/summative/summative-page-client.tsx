'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';

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
  const router = useRouter();
  // Bumping the key remounts the container with fresh state — used to reset
  // a failed attempt without a hard page reload that would also blow away
  // unrelated client state (issue #2226).
  const [retryKey, setRetryKey] = useState(0);

  return (
    <main className="min-h-screen bg-stone-50">
      <div className="py-8">
        <SummativeAssessmentContainer
          key={retryKey}
          moduleId={moduleId}
          language={language}
          country={country}
          level={level}
          onComplete={() => {
            router.push(`/${locale}/modules`);
          }}
          onRetry={() => {
            setRetryKey((k) => k + 1);
          }}
        />
      </div>
    </main>
  );
}
