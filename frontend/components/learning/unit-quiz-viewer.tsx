'use client';

import { useRouter } from '@/i18n/routing';
import { QuizContainer } from '@/components/quiz/quiz-container';

interface UnitQuizViewerProps {
  moduleId: string;
  unitId: string;
  language: 'fr' | 'en';
  level: number;
  unitTitle?: string;
  unitDescription?: string | null;
}

export function UnitQuizViewer({
  moduleId,
  unitId,
  language,
  level,
  unitTitle,
  unitDescription,
}: UnitQuizViewerProps) {
  const router = useRouter();

  return (
    <div>
      {unitTitle && (
        <div className="mb-4">
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900 mb-1">
            {unitTitle}
          </h1>
          <p className="text-sm text-gray-500">{`Unit ${unitId}`}</p>
          {unitDescription && (
            <p className="text-base text-gray-700 mt-2">{unitDescription}</p>
          )}
        </div>
      )}
      <QuizContainer
        moduleId={moduleId}
        unitId={unitId}
        language={language}
        level={level}
        onComplete={() => router.push(`/modules/${moduleId}`)}
      />
    </div>
  );
}
