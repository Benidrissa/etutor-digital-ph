'use client';

import { useRouter } from '@/i18n/routing';
import { QuizContainer } from '@/components/quiz/quiz-container';

interface UnitQuizViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
}

export function UnitQuizViewer({ moduleId, unitId, language, level }: UnitQuizViewerProps) {
  const router = useRouter();

  return (
    <QuizContainer
      moduleId={moduleId}
      unitId={unitId}
      language={language}
      level={level}
      onComplete={() => router.push(`/modules/${moduleId}`)}
    />
  );
}
