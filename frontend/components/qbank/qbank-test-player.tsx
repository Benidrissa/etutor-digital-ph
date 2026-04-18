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
  const questionStartTime = useRef<number>(0);

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

  // Toggle an option in the current question's selection. Multi-answer questions
  // need to accumulate picks before scoring — training-mode feedback is deferred
  // to an explicit "Valider" step rather than firing on first click (#1632).
  const handleToggle = useCallback((optionIndex: number) => {
    if (!currentQuestion || showingFeedback) return;

    const timeSec = recordTime();
    setAnswers((prev) => {
      const existing = prev[currentQuestion.id]?.selected ?? [];
      const next = existing.includes(optionIndex)
        ? existing.filter((i) => i !== optionIndex)
        : [...existing, optionIndex];
      return {
        ...prev,
        [currentQuestion.id]: { selected: next, time_sec: timeSec },
      };
    });
  }, [currentQuestion, showingFeedback, recordTime]);

  // Commit the training-mode answer: stop the timer and reveal the correct set.
  // "Question suivante" then unlocks normally via the existing flow.
  const handleValidate = useCallback(() => {
    if (!currentQuestion) return;
    const timeSec = recordTime();
    setAnswers((prev) => {
      const existing = prev[currentQuestion.id];
      if (!existing) return prev;
      return {
        ...prev,
        [currentQuestion.id]: { ...existing, time_sec: timeSec },
      };
    });
    setTimerRunning(false);
    setShowingFeedback(true);
  }, [currentQuestion, recordTime]);

  const handleTimerExpire = useCallback(() => {
    if (!currentQuestion) return;
    const timeSec = recordTime();
    const hadAnswer = Boolean(answers[currentQuestion.id]);
    setAnswers((prev) => {
      if (prev[currentQuestion.id]) return prev;
      return { ...prev, [currentQuestion.id]: { selected: [], time_sec: timeSec } };
    });
    setTimerRunning(false);

    // In training+feedback mode, if the learner had already picked something,
    // lock in what they have and reveal the correct set instead of skipping.
    // Otherwise (no pick, or exam mode) advance like before.
    if (testData?.mode === 'training' && testData.show_feedback && hadAnswer) {
      setShowingFeedback(true);
      return;
    }

    if (testData && currentIndex < testData.questions.length - 1) {
      setTimeout(() => goToNext(), 500);
    }
  }, [currentQuestion, recordTime, testData, currentIndex, goToNext, answers]);

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
  const selectedIndices = answers[currentQuestion.id]?.selected ?? [];
  const hasSelection = selectedIndices.length > 0;
  const isLastQuestion = currentIndex === totalQuestions - 1;
  const isExamMode = testData.mode === 'exam';
  const isTrainingWithFeedback =
    testData.mode === 'training' && testData.show_feedback;
  const hasTimer = testData.time_per_question_sec > 0 && testData.mode !== 'review';
  // correct_answer_indices is only on the payload in training+feedback mode.
  // Review mode doesn't need it (that page fetches its own review data).
  const correctIndices = isTrainingWithFeedback
    ? (currentQuestion.correct_answer_indices ?? undefined)
    : undefined;

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
        selectedIndices={selectedIndices}
        onToggle={handleToggle}
        showFeedback={showingFeedback || testData.mode === 'review'}
        correctIndices={correctIndices}
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

        {/* Training + show_feedback: commit the selection explicitly before advancing.
            Lets the learner pick every correct option on multi-answer questions. */}
        {isTrainingWithFeedback && !showingFeedback && hasSelection && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={handleValidate}
          >
            {t('validate')}
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

        {!showingFeedback && !isExamMode && !isTrainingWithFeedback && hasSelection && !isLastQuestion && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={goToNext}
          >
            {t('nextQuestion')}
          </Button>
        )}

        {isExamMode && !isLastQuestion && hasSelection && (
          <Button
            className="min-h-[44px] flex-1"
            onClick={goToNext}
          >
            {t('nextQuestion')}
          </Button>
        )}

        {((isLastQuestion && hasSelection && !showingFeedback && !isTrainingWithFeedback) ||
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
