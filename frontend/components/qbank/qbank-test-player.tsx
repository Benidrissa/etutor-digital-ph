'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { ArrowLeft, ArrowRight, Check } from 'lucide-react';
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

// Delay before auto-advancing after a committed answer. Enough for the
// learner to register what they picked without hand-holding them to click.
const AUTO_ADVANCE_MS = 700;
// Longer delay in training+feedback mode so the learner can read the
// correct answer and the explanation before moving on.
const AUTO_ADVANCE_FEEDBACK_MS = 2000;

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
  const autoAdvanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  useEffect(() => () => {
    if (autoAdvanceTimer.current) clearTimeout(autoAdvanceTimer.current);
  }, []);

  const currentQuestion = testData?.questions[currentIndex] ?? null;

  const recordTime = useCallback(() => {
    return Math.round((Date.now() - questionStartTime.current) / 1000);
  }, []);

  const cancelAutoAdvance = useCallback(() => {
    if (autoAdvanceTimer.current) {
      clearTimeout(autoAdvanceTimer.current);
      autoAdvanceTimer.current = null;
    }
  }, []);

  const goToNext = useCallback(() => {
    if (!testData) return;
    cancelAutoAdvance();
    setShowingFeedback(false);
    if (currentIndex < testData.questions.length - 1) {
      setCurrentIndex((prev) => prev + 1);
      setTimerResetKey((prev) => prev + 1);
      questionStartTime.current = Date.now();
      if (testData.mode === 'exam') {
        setTimerRunning(true);
      }
    }
  }, [testData, currentIndex, cancelAutoAdvance]);

  const handleSubmit = useCallback(async () => {
    if (!testData) return;
    cancelAutoAdvance();
    setPhase('submitting');
    try {
      const res = await submitQBankTest(testId, answers);
      setResult(res);
      setPhase('done');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Submit failed');
      setPhase('playing');
    }
  }, [testId, testData, answers, cancelAutoAdvance]);

  // Commit an answer and either advance or submit after a short delay so
  // the learner isn't forced to click a separate "Next" button on every
  // question while the timer is ticking (#1671).
  const scheduleAutoAdvance = useCallback((delay: number) => {
    cancelAutoAdvance();
    autoAdvanceTimer.current = setTimeout(() => {
      autoAdvanceTimer.current = null;
      if (!testData) return;
      const isLast = currentIndex === testData.questions.length - 1;
      if (isLast) {
        void handleSubmit();
      } else {
        goToNext();
      }
    }, delay);
  }, [cancelAutoAdvance, testData, currentIndex, goToNext, handleSubmit]);

  // Toggle an option in the current question's selection. Multi-answer
  // questions accumulate picks and commit via Valider; single-answer
  // modes auto-advance on the first tap.
  const handleToggle = useCallback((optionIndex: number) => {
    if (!currentQuestion || showingFeedback) return;

    const timeSec = recordTime();
    const optionCount = currentQuestion.options.length;
    const isMultiAnswer = optionCount > 2;
    const isTrainingWithFeedback =
      testData?.mode === 'training' && testData.show_feedback;

    setAnswers((prev) => {
      const existing = prev[currentQuestion.id]?.selected ?? [];
      // For binary questions (OUI/NON style) treat each tap as a fresh
      // single-answer pick so the UI behaves like a radio group.
      const next = isMultiAnswer
        ? (existing.includes(optionIndex)
            ? existing.filter((i) => i !== optionIndex)
            : [...existing, optionIndex])
        : [optionIndex];
      return {
        ...prev,
        [currentQuestion.id]: { selected: next, time_sec: timeSec },
      };
    });

    // Auto-advance only for the simple cases: non-multi questions in
    // exam or no-feedback training. Multi-answer questions still need
    // Valider so the learner can pick every correct option.
    if (isMultiAnswer) return;
    if (isTrainingWithFeedback) return;
    scheduleAutoAdvance(AUTO_ADVANCE_MS);
  }, [currentQuestion, showingFeedback, recordTime, testData, scheduleAutoAdvance]);

  // Commit the training-mode answer: stop the timer, reveal the correct
  // set, then auto-advance after a feedback-reading delay.
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
    scheduleAutoAdvance(AUTO_ADVANCE_FEEDBACK_MS);
  }, [currentQuestion, recordTime, scheduleAutoAdvance]);

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
      scheduleAutoAdvance(AUTO_ADVANCE_FEEDBACK_MS);
      return;
    }

    if (testData && currentIndex < testData.questions.length - 1) {
      scheduleAutoAdvance(500);
    } else if (testData) {
      scheduleAutoAdvance(500);
    }
  }, [currentQuestion, recordTime, testData, currentIndex, answers, scheduleAutoAdvance]);

  const handlePrevious = useCallback(() => {
    if (currentIndex > 0) {
      cancelAutoAdvance();
      setShowingFeedback(false);
      setCurrentIndex((prev) => prev - 1);
      setTimerResetKey((prev) => prev + 1);
      questionStartTime.current = Date.now();
      if (testData?.mode === 'exam') {
        setTimerRunning(true);
      }
    }
  }, [currentIndex, testData, cancelAutoAdvance]);

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
  const isMultiAnswer = currentQuestion.options.length > 2;
  const hasTimer = testData.time_per_question_sec > 0 && testData.mode !== 'review';
  // correct_answer_indices is only on the payload in training+feedback mode.
  // Review mode doesn't need it (that page fetches its own review data).
  const correctIndices = isTrainingWithFeedback
    ? (currentQuestion.correct_answer_indices ?? undefined)
    : undefined;

  // Multi-answer questions need Valider to commit every correct pick
  // before scoring; binary questions auto-advance on the first tap.
  const showValidate =
    isTrainingWithFeedback && !showingFeedback && isMultiAnswer && hasSelection;
  // Show Submit only on the last question — intermediate submits are covered
  // by the auto-advance timer kicking through to handleSubmit.
  const showSubmit =
    isLastQuestion &&
    ((isExamMode && hasSelection) || showingFeedback || (isMultiAnswer && hasSelection));

  return (
    <div className="mx-auto flex h-[calc(100dvh-var(--header-offset,0px))] w-full max-w-2xl flex-col gap-3 px-3 pb-3 pt-3 sm:gap-4 sm:px-4 sm:pt-4">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground sm:text-sm">
          <span>{t('question', { current: currentIndex + 1, total: totalQuestions })}</span>
          {testData.title && (
            <span className="ml-2 truncate font-medium text-foreground">
              {testData.title}
            </span>
          )}
        </div>
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted sm:h-1.5">
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

      <div className="min-h-0 flex-1 overflow-y-auto">
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
      </div>

      <div
        className="sticky bottom-0 -mx-3 flex items-center gap-2 border-t border-border bg-background/95 px-3 py-2 backdrop-blur sm:-mx-4 sm:px-4"
        style={{ paddingBottom: 'max(0.5rem, env(safe-area-inset-bottom))' }}
      >
        {!isExamMode && (
          <Button
            variant="outline"
            size="icon"
            className="h-11 w-11 shrink-0"
            onClick={handlePrevious}
            disabled={currentIndex === 0}
            aria-label={t('previousQuestion')}
            title={t('previousQuestion')}
          >
            <ArrowLeft className="h-5 w-5" />
          </Button>
        )}

        {showValidate && (
          <Button
            className="h-11 flex-1"
            onClick={handleValidate}
          >
            <Check className="h-5 w-5" />
            {t('validate')}
          </Button>
        )}

        {showSubmit && !showValidate && (
          <Button
            className={cn('h-11', isExamMode ? 'flex-1' : 'flex-1')}
            onClick={handleSubmit}
          >
            {t('submitTest')}
          </Button>
        )}

        {!showValidate && !showSubmit && !isExamMode && (
          <Button
            variant="outline"
            size="icon"
            className="ml-auto h-11 w-11 shrink-0"
            onClick={goToNext}
            disabled={isLastQuestion}
            aria-label={t('nextQuestion')}
            title={t('nextQuestion')}
          >
            <ArrowRight className="h-5 w-5" />
          </Button>
        )}

        {/* Exam mode has no prev/next text labels — auto-advance handles
            the flow and manual skip would let learners cheat the timer. */}
        {isExamMode && !showSubmit && (
          <div className="flex-1" aria-hidden="true" />
        )}
      </div>
    </div>
  );
}
