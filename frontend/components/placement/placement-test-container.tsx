'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { PlacementTestIntro } from './placement-test-intro';
import { PlacementTestInterface } from './placement-test-interface';
import { PlacementTestResults } from './placement-test-results';

type PlacementTestState = 'intro' | 'assessment' | 'results' | 'skipped';

interface PlacementTestContainerProps {
  locale: string;
}

interface PlacementTestResult {
  assigned_level: number;
  score_percentage: number;
  competency_areas: string[];
  recommendations: string[];
  level_description: { en: string; fr: string };
  can_retake_after?: string;
  skipped?: boolean;
}

export function PlacementTestContainer({ locale }: PlacementTestContainerProps) {
  const t = useTranslations('PlacementTest');
  const [state, setState] = useState<PlacementTestState>('intro');
  const [result, setResult] = useState<PlacementTestResult | null>(null);

  const handleStartTest = () => {
    setState('assessment');
  };

  const handleSkipTest = async () => {
    try {
      const response = await fetch('/api/v1/placement-test/skip', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('token')}`,
        },
      });

      if (!response.ok) {
        throw new Error('Failed to skip placement test');
      }

      const skipResult = await response.json();
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
        />
      );

    case 'assessment':
      return (
        <PlacementTestInterface
          onComplete={handleTestComplete}
          locale={locale}
        />
      );

    case 'results':
    case 'skipped':
      return (
        <PlacementTestResults
          result={result!}
          locale={locale}
          isSkipped={state === 'skipped'}
        />
      );

    default:
      return null;
  }
}