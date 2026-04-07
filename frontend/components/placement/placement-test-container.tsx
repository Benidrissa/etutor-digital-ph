'use client';

import { useState } from 'react';
import { PlacementTestIntro } from './placement-test-intro';
import { PlacementTestInterface } from './placement-test-interface';
import { PlacementTestResults } from './placement-test-results';

type PlacementTestState = 'intro' | 'assessment' | 'results' | 'skipped';

interface PlacementTestContainerProps {
  locale: string;
  courseId?: string;
  courseName?: string;
}

interface PlacementTestResult {
  assigned_level: number;
  score_percentage: number;
  level_scores: Record<string, number>;
  competency_areas: string[];
  recommendations: string[];
  can_retake_after?: string;
  course_id?: string;
  skipped?: boolean;
}

export function PlacementTestContainer({ locale, courseId, courseName }: PlacementTestContainerProps) {
  const [state, setState] = useState<PlacementTestState>('intro');
  const [result, setResult] = useState<PlacementTestResult | null>(null);

  const handleStartTest = () => {
    setState('assessment');
  };

  const handleSkipTest = async () => {
    try {
      const skipUrl = courseId
        ? `/api/v1/courses/${courseId}/preassessment/skip`
        : '/api/v1/placement-test/skip';
      const { authClient } = await import('@/lib/auth');
      const skipResult = await authClient.authenticatedFetch<PlacementTestResult>(skipUrl, {
        method: 'POST',
      });
      setResult(skipResult);
      setState('skipped');
    } catch (error) {
      console.error('Failed to skip placement test:', error);
    }
  };

  const handleTestComplete = (testResult: PlacementTestResult) => {
    setResult(testResult);
    setState('results');
  };

  switch (state) {
    case 'intro':
      return (
        <PlacementTestIntro
          onStartTest={handleStartTest}
          onSkipTest={handleSkipTest}
          locale={locale}
          courseId={courseId}
          courseName={courseName}
        />
      );

    case 'assessment':
      return (
        <PlacementTestInterface
          onComplete={handleTestComplete}
          locale={locale}
          courseId={courseId}
        />
      );

    case 'results':
    case 'skipped':
      return (
        <PlacementTestResults
          result={result!}
          locale={locale}
          courseId={courseId}
          isSkipped={state === 'skipped'}
        />
      );

    default:
      return null;
  }
}