'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { QBankQuestionTimer } from './qbank-question-timer';
import { QBankImageQuestion } from './qbank-image-question';
import { QBankTestResults } from './qbank-test-results';
import {
  startQBankTest,
  submitQBankTest,
  type QBankTestStartResponse,
  type QBankTestAttemptResponse,
} from '@/lib/api';

type Phase = 'loading' | 'playing' | 'submitting' | 'done';

interface QBankTestPlayerProps {
  testId: string;
}

export function QBankTestPlayer({ testId }: QBankTestPlayerProps) {
  const t = useTranslations('qbank');
  const [phase, setPhase] = useState<Phase>('loading');
  const [testData, setTestData] = useState<QBankTestStartResponse | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, { selected: number[]; time_sec: number }>>({});
  const [result, setResult] = useState<QBankTestAttemptResponse | null>(null);
  const [timerResetKey, setTimerResetKey] = useState(0);
  const [timerRunning, setTimerRunning] = useState(false);
  const [showingFeedback, setShowingFeedback] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const questionStartTime = useRef<number>(Date.now());

  useEffect(() => {
    startQBankTest(testId)
      .then((data) => {
        setTestData(data);
        setPhase('playing');
        questionStartTime.current = Date.now();
        if (data.mode === 'exam') {
          setTimerRunning(true);
        }
      })
      .catch((err) => {
        setError(err.message || 'Failed to load test');
      });
  }, [testId]);

  const currentQuestion = testData?.questions[currentIndex] ?? null;

  const recordTime = useCallback(() => {
    return Math.round((Date.now() - questionStartTime.current) / 1000);
  }, []);

  const goToNext = useCallback(() => {
    if (!testData) return;
    setShowingFeedback(false);
    if (currentIndex < testData.questions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
      setTimerResetKey((prev) => prev + 1);
      questionStartTime.current = Date.now();
      if (testData.mode === 'exam') {
        setTimerRunning(true);
      }
    }
  }, [testData, currentIndex]);

  const handleSelect = useCallback((optionIndex: number) => {
    if (!currentQuestion || showingFeedback) return;

    const timeSec = recordTime();
    setAnswers((prev) => ({
      ...prev,
      [currentQuestion.id]: { selected: [optionIndex], time_sec: timeSec },
    }));

    if (testData?.mode === 'training' && testData.show_feedback) {
      setTimerRunning(false);
      setShowingFeedback(true);
    }
  }, [currentQuestion, showingFeedback, recordTime, testData]);

  const handleTimerExpire = useCallback(() => {
    if (!currentQuestion) return;
    const timeSec = recordTime();
    setAnswers((prev) => {
      if (prev[currentQuestion.id]) return prev;
      return { ...prev, [currentQuestion.id]: { selected: [], time_sec: timeSec } };
    });
    setTimerRunning(false);

    if (testData && currentIndex < testData.questions.length - 1) {
      setTimeout(() => goToNext(), 500);
    }
  }, [currentQuestion, recordTime, testData, currentIndex, goToNext]);

  const handleSubmit = useCallback(async () => {
    if (!testData) return;
    setPhase('submitting');
    try {
      const res = await submitQBankTest(testId, answers);
      setResult(res);
      setPhase('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submit failed');
      setPhase('playing');
    }
  }, [testId, testData, answers]);

  const handlePrevious = useCallback(() => {
    if (currentIndex > 0) {
      setShowingFeedback(false);
      setCurrentIndex((prev) => prev - 1);
      setTimerResetKey((prev) => prev + 1);
      questionStartTime.current = Date.now();
      if (testData?.mode === 'exam') {
        setTimerRunning(true);
      }
    }
  }, [currentIndex, testData]);

  if (error) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center px-4">
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  if (phase === 'loading') {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4">
        <LoadingSpinner className="h-8 w-8" />
        <p className="text-muted-foreground">{t('loading')}</p>
      </div>
    );
  }

  if (phase === 'done' && result) {
    return <QBankTestResults attempt={result} testId={testId} />;
  }

  if (phase === 'submitting') {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4">
        <LoadingSpinner className="h-8 w-8" />
        <p className="text-muted-foreground">{t('submitTest')}...</p>
      </div>
    );
  }

  if (!testData || !currentQuestion) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center px-4">
        <p className="text-muted-foreground">{t('noQuestions')}</p>
      </div>
    );
  }

  const totalQuestions = testData.questions.length;
  const progressPercent = ((currentIndex + 1) / totalQuestions) * 100;
  const selectedOption = answers[currentQuestion.id]?.selected[0] ?? null;
  const isLastQuestion = currentIndex === totalQuestions - 1;
  const isExamMode = testData.mode === 'exam';
  const hasTimer = testData.time_per_question_sec > 0 && testData.mode !== 'review';

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{t('question', { current: currentIndex + 1, total: totalQuestions })}</span>
          {testData.title && <span className="truncate ml-2 font-medium text-foreground">{testData.title}</span>}
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {hasTimer && (
        <QBankQuestionTimer
          totalSeconds={testData.time_per_question_sec}
          onExpire={handleTimerExpire}
          isRunning={timerRunning && !showingFeedback}
          resetKey={timerResetKey}
        />
      )}

      <QBankImageQuestion
        question={currentQuestion}
        selectedOption={selectedOption}
        onSelect={handleSelect}
        showFeedback={showingFeedback || testData.mode === 'review'}
        correctIndices={testData.mode === 'review' ? [] : undefined}
        onImageLoad={() => {
          if (hasTimer && !showingFeedback) {
            setTimerRunning(true);
          }
        }}
      />

      <div className="flex items-center gap-3 pt-2">
        {!isExamMode && (
          <Button
            variant="outline"
            className="min-h-[44px] flex-1"
            onClick={handlePrevious}
            disabled={currentIndex === 0}
          >
            {t('previousQuestion')}
          </Button>
        )}

        {showingFeedback && !isLastQuestion && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={goToNext}
          >
            {t('nextQuestion')}
          </Button>
        )}

        {!showingFeedback && !isExamMode && selectedOption !== null && !isLastQuestion && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={goToNext}
          >
            {t('nextQuestion')}
          </Button>
        )}

        {isExamMode && !isLastQuestion && selectedOption !== null && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={goToNext}
          >
            {t('nextQuestion')}
          </Button>
        )}

        {((isLastQuestion && selectedOption !== null && !showingFeedback) ||
          (isLastQuestion && showingFeedback)) && (
          <Button
            className={cn('min-h-[44px]', isExamMode ? 'w-full' : 'flex-1')}
            onClick={handleSubmit}
          >
            {t('submitTest')}
          </Button>
        )}
      </div>
    </div>
  );
}
