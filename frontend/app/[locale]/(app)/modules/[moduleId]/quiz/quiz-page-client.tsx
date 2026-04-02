'use client';

import { useRouter } from '@/i18n/routing';
import { QuizContainer } from '@/components/quiz/quiz-container';

interface QuizPageClientProps {
  moduleId: string;
  unitId: string;
  language: string;
  level: number;
}

export function QuizPageClient({
  moduleId,
  unitId,
  language,
  level,
}: QuizPageClientProps) {
  const router = useRouter();

  const handleQuizComplete = () => {
    router.push(`/modules/${moduleId}`);
  };

  return (
    <QuizContainer
      moduleId={moduleId}
      unitId={unitId}
      language={language}
      level={level}
      onComplete={handleQuizComplete}
    />
  );
}
