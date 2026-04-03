'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Loader2, AlertTriangle, Play, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { QuizInterface } from './quiz-interface';
import { QuizResults } from './quiz-results';
import type { Quiz, QuizAttemptResponse } from '@/lib/api';
import { generateQuiz, apiFetch } from '@/lib/api';
import { useSettings } from '@/lib/settings-context';
import { useCurrentUser } from '@/lib/hooks/use-current-user';

const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 3 * 60 * 1000;

interface QuizContainerProps {
  moduleId: string;
  unitId: string;
  language: string;
  country?: string;
  level: number;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

interface GeneratingResponse {
  status: 'generating';
  task_id: string;
  message: string;
}

type QuizState = 'loading' | 'generating' | 'ready' | 'in-progress' | 'completed' | 'error';

export function QuizContainer({
  moduleId,
  unitId,
  language,
  country,
  level,
  onComplete,
  onError
}: QuizContainerProps) {
  const t = useTranslations('Quiz');
  const { getSetting } = useSettings();
  const unitQuestionsCount = getSetting<number>("quiz.unit_questions_count", 10);
  const currentUser = useCurrentUser();
  const resolvedCountry = country || currentUser?.country || 'SN';
  
  const [state, setState] = useState<QuizState>('loading');
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [result, setResult] = useState<QuizAttemptResponse | null>(null);
  const [error, setError] = useState<string>('');
  const [retryCount, setRetryCount] = useState(0);
  const [forceRegenerate, setForceRegenerate] = useState(false);

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartRef = useRef<number>(0);

  const pollStatus = (taskId: string, startTime: number) => {
    if (Date.now() - startTime > POLL_TIMEOUT_MS) {
      setState('error');
      const msg = t('generationTimeout');
      setError(msg);
      onError?.(msg);
      return;
    }

    pollTimerRef.current = setTimeout(async () => {
      try {
        const statusRes = await apiFetch<{ status: string; content_id?: string; error?: string }>(
          `/api/v1/content/status/${taskId}`
        );

        if (statusRes.status === 'complete') {
          const quizData = await generateQuiz({
            module_id: moduleId,
            unit_id: unitId,
            language,
            country: resolvedCountry,
            level,
            num_questions: unitQuestionsCount,
          });
          setQuiz(quizData);
          setForceRegenerate(false);
          setState('ready');
        } else if (statusRes.status === 'failed') {
          const msg = t('generationFailed');
          setError(msg);
          setState('error');
          onError?.(msg);
        } else {
          pollStatus(taskId, startTime);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : t('failedToLoad');
        setError(errorMessage);
        setState('error');
        onError?.(errorMessage);
      }
    }, POLL_INTERVAL_MS);
  };

  useEffect(() => {
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    };
  }, []);
  
  useEffect(() => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);

    const fetchQuiz = async () => {
      try {
        setState('loading');
        setError('');
        
        const rawData = await generateQuiz({
          module_id: moduleId,
          unit_id: unitId,
          language,
          country: resolvedCountry,
          level,
          num_questions: unitQuestionsCount,
          force_regenerate: forceRegenerate,
        }) as Quiz | GeneratingResponse;

        if ('status' in rawData && rawData.status === 'generating') {
          setState('generating');
          pollStartRef.current = Date.now();
          pollStatus((rawData as GeneratingResponse).task_id, pollStartRef.current);
        } else {
          setQuiz(rawData as Quiz);
          setForceRegenerate(false);
          setState('ready');
        }
      } catch (err) {
        console.error('Failed to load quiz:', err);
        const errorMessage = err instanceof Error ? err.message : t('failedToLoad');
        setError(errorMessage);
        setState('error');
        onError?.(errorMessage);
      }
    };
    
    fetchQuiz();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moduleId, unitId, language, resolvedCountry, level, retryCount, forceRegenerate]);
  
  const handleStartQuiz = () => {
    setState('in-progress');
  };
  
  const handleQuizComplete = (quizResult: QuizAttemptResponse) => {
    setResult(quizResult);
    setState('completed');
  };
  
  const handleQuizError = (errorMessage: string) => {
    setError(errorMessage);
    setState('error');
    onError?.(errorMessage);
  };
  
  const handleRetry = () => {
    setResult(null);
    setQuiz(null);
    setRetryCount(prev => prev + 1);
  };

  const handleRefreshContent = () => {
    setResult(null);
    setQuiz(null);
    setForceRegenerate(true);
  };
  
  const handleContinue = () => {
    onComplete?.();
  };
  
  // Loading State
  if (state === 'loading') {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-teal-600 mb-4" />
            <h2 className="text-lg font-semibold text-stone-900 mb-2">
              {t('generating')}
            </h2>
            <p className="text-stone-600 text-center max-w-md">
              {t('loading')}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Generating State (async Celery task polling)
  if (state === 'generating') {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Loader2 className="w-8 h-8 animate-spin text-teal-600 mb-4" />
            <h2 className="text-lg font-semibold text-stone-900 mb-2">
              {t('generatingContent')}
            </h2>
            <p className="text-stone-600 text-center max-w-md">
              {t('generatingDescription')}
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  // Error State
  if (state === 'error') {
    return (
      <div className="max-w-4xl mx-auto p-4">
        <Card className="border-red-200 bg-red-50">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <AlertTriangle className="w-8 h-8 text-red-600 mb-4" />
            <h2 className="text-lg font-semibold text-red-900 mb-2">
              {t('error')}
            </h2>
            <p className="text-red-700 text-center max-w-md mb-6">
              {error || t('networkError')}
            </p>
            <Button onClick={handleRetry} variant="outline">
              {t('tryAgain')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  // Ready to Start State
  if (state === 'ready' && quiz) {
    return (
      <div className="max-w-4xl mx-auto p-4 space-y-6">
        <Card>
          <CardHeader className="text-center">
            <CardTitle className="text-2xl text-stone-900">
              {quiz.content.title}
            </CardTitle>
            {quiz.content.description && (
              <p className="text-stone-600 mt-2">
                {quiz.content.description}
              </p>
            )}
          </CardHeader>
          
          <CardContent className="space-y-6">
            {/* Quiz Info */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-center">
              <div className="p-4 bg-stone-50 rounded-lg">
                <div className="text-2xl font-bold text-stone-900">
                  {quiz.content.questions.length}
                </div>
                <div className="text-sm text-stone-600">{t('questions')}</div>
              </div>
              
              {quiz.content.time_limit_minutes && (
                <div className="p-4 bg-stone-50 rounded-lg">
                  <div className="text-2xl font-bold text-stone-900">
                    {quiz.content.time_limit_minutes}
                  </div>
                  <div className="text-sm text-stone-600">{t('minutes')}</div>
                </div>
              )}
              
              <div className="p-4 bg-stone-50 rounded-lg">
                <div className="text-2xl font-bold text-stone-900">
                  {quiz.content.passing_score}%
                </div>
                <div className="text-sm text-stone-600">
                  {t('passingScore', { score: quiz.content.passing_score })}
                </div>
              </div>
            </div>
            
            {/* Instructions */}
            <Card className="bg-blue-50 border-blue-200">
              <CardContent className="p-4">
                <p className="text-blue-800 text-center">
                  {t('quizInstructions')}
                </p>
              </CardContent>
            </Card>
            
            {/* Start Button */}
            <div className="text-center">
              <Button 
                onClick={handleStartQuiz}
                size="lg"
                className="min-h-11 px-8"
              >
                <Play className="w-4 h-4 mr-2" />
                {t('startQuiz')}
              </Button>
            </div>
            
            {/* Additional Info */}
            <div className="flex flex-wrap gap-2 justify-center items-center">
              <Badge variant="outline">
                {t('level')} {level}
              </Badge>
              {quiz.cached && (
                <Badge variant="secondary">
                  {t('cached')}
                </Badge>
              )}
              <Badge variant="outline">
                {language.toUpperCase()}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleRefreshContent}
                className="min-h-11 gap-1.5 text-stone-500 hover:text-stone-900"
              >
                <RefreshCw className="w-4 h-4" />
                <span className="hidden sm:inline">{t('refreshContent')}</span>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }
  
  // In Progress State
  if (state === 'in-progress' && quiz) {
    return (
      <QuizInterface
        quiz={quiz}
        onComplete={handleQuizComplete}
        onError={handleQuizError}
      />
    );
  }
  
  // Completed State
  if (state === 'completed' && quiz && result) {
    return (
      <QuizResults
        quiz={quiz}
        result={result}
        onRetry={handleRetry}
        onContinue={handleContinue}
      />
    );
  }
  
  return null;
}