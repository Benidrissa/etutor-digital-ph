'use client';

import { useRouter } from 'next/navigation';
import { QuizContainer } from './quiz-container';

interface QuizPageClientProps {
  moduleId: string;
  unitId: string;
  language: string;
  moduleBackPath: string;
}

export function QuizPageClient({ moduleId, unitId, language, moduleBackPath }: QuizPageClientProps) {
  const router = useRouter();

  return (
    <QuizContainer
      moduleId={moduleId}
      unitId={unitId}
      language={language}
      country="SN"
      level={1}
      onComplete={() => router.push(moduleBackPath)}
    />
  );
}
