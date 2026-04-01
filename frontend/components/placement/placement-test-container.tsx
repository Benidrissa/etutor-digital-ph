'use client';

import { useState, useEffect } from 'react';
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
  raw_score: number;
  adjusted_score: number;
  domain_scores: Record<string, number>;
  competency_areas: string[];
  recommendations: string[];
  attempted_at: string;
  can_retake_after: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export function PlacementTestContainer({ locale }: PlacementTestContainerProps) {
  const [state, setState] = useState<PlacementTestState>('intro');
  const [result, setResult] = useState<PlacementTestResult | null>(null);
  const [previousAttempt, setPreviousAttempt] = useState<PreviousAttempt | null>(null);
  const [loadingPrevious, setLoadingPrevious] = useState(true);

  useEffect(() => {
    const fetchPreviousResult = async () => {
      try {
        const token = localStorage.getItem('access_token');
        if (!token) {
          setLoadingPrevious(false);
          return;
        }
        const response = await fetch(`${API_BASE}/api/v1/placement-test/results`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (response.ok) {
          const data = await response.json();
          setPreviousAttempt(data);
        }
      } catch {
        // silently ignore — no previous result
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
      const response = await fetch(`${API_BASE}/api/v1/placement-test/skip`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
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
