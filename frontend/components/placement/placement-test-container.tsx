'use client';

import { useState, useEffect } from 'react';
import { authClient } from '@/lib/auth';
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

export interface PreviousAttempt {
  id: string;
  assigned_level: number;
  score_percentage: number;
  domain_scores: Record<string, number>;
  competency_areas: string[];
  recommendations: string[];
  can_retake_after: string | null;
  attempted_at: string;
}

export function PlacementTestContainer({ locale }: PlacementTestContainerProps) {
  const [state, setState] = useState<PlacementTestState>('intro');
  const [result, setResult] = useState<PlacementTestResult | null>(null);
  const [previousAttempt, setPreviousAttempt] = useState<PreviousAttempt | null>(null);
  const [loadingPrevious, setLoadingPrevious] = useState(true);

  useEffect(() => {
    const fetchPreviousResult = async () => {
      try {
        const data = await authClient.authenticatedFetch<PreviousAttempt | null>(
          '/api/v1/placement-test/results'
        );
        setPreviousAttempt(data);
      } catch {
        // No previous result or not authenticated — stay null
      } finally {
        setLoadingPrevious(false);
      }
    };

    fetchPreviousResult();
  }, []);

  const handleStartTest = () => {
    setState('assessment');
  };

  const handleSkipTest = async () => {
    try {
      const skipResult = await authClient.authenticatedFetch<PlacementTestResult>(
        '/api/v1/placement-test/skip',
        { method: 'POST' }
      );
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
          previousAttempt={previousAttempt}
          loadingPrevious={loadingPrevious}
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