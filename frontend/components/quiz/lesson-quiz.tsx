'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import {
  CheckCircle,
  XCircle,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  RotateCcw,
  BookOpen,
  Trophy,
  Target,
  Loader2,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import type {
  Quiz,
  QuizAnswerSubmission,
  QuizAttemptResponse,
} from '@/lib/api';
import { submitQuizAttempt, completeLessonAfterQuiz } from '@/lib/api';

type LessonQuizStage = 'quiz' | 'results';

interface QuestionState {
  selectedOption: number | null;
  timeSpentSeconds: number;
  showFeedback: boolean;
}

interface LessonQuizProps {
  quiz: Quiz;
  moduleId: string;
  unitId: string;
  onRetry: () => void;
  onReviewLesson: () => void;
  onComplete: () => void;
}

export function LessonQuiz({
  quiz,
  moduleId,
  unitId,
  onRetry,
  onReviewLesson,
  onComplete,
}: LessonQuizProps) {
  const t = useTranslations('LessonQuiz');

  const [stage, setStage] = useState<LessonQuizStage>('quiz');
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [questionStates, setQuestionStates] = useState<QuestionState[]>(
    quiz.content.questions.map(() => ({
      selectedOption: null,
      timeSpentSeconds: 0,
      showFeedback: false,
    }))
  );
  const [startTime] = useState(Date.now());
  const [questionStartTime, setQuestionStartTime] = useState(Date.now());
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isMarkingComplete, setIsMarkingComplete] = useState(false);
  const [result, setResult] = useState<QuizAttemptResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const totalQuestions = quiz.content.questions.length;
  const currentQuestion = quiz.content.questions[currentQuestionIndex];
  const currentState = questionStates[currentQuestionIndex];
  const progressPercent = ((currentQuestionIndex + 1) / totalQuestions) * 100;
  const isLastQuestion = currentQuestionIndex === totalQuestions - 1;

  useEffect(() => {
    if (currentState.showFeedback) return;

    const interval = setInterval(() => {
      setQuestionStates((prev) =>
        prev.map((state, index) =>
          index === currentQuestionIndex
            ? {
                ...state,
                timeSpentSeconds: Math.floor(
                  (Date.now() - questionStartTime) / 1000
                ),
              }
            : state
        )
      );
    }, 1000);

    return () => clearInterval(interval);
  }, [currentQuestionIndex, questionStartTime, currentState.showFeedback]);

  useEffect(() => {
    setQuestionStartTime(Date.now());
  }, [currentQuestionIndex]);

  const handleOptionSelect = useCallback(
    (optionIndex: number) => {
      if (currentState.showFeedback) return;

      setQuestionStates((prev) =>
        prev.map((state, index) =>
          index === currentQuestionIndex
            ? { ...state, selectedOption: optionIndex }
            : state
        )
      );
    },
    [currentQuestionIndex, currentState.showFeedback]
  );

  const handleSubmitAnswer = useCallback(() => {
    if (currentState.selectedOption === null) return;

    const timeSpent = Math.floor((Date.now() - questionStartTime) / 1000);
    setQuestionStates((prev) =>
      prev.map((state, index) =>
        index === currentQuestionIndex
          ? { ...state, showFeedback: true, timeSpentSeconds: timeSpent }
          : state
      )
    );
  }, [currentQuestionIndex, currentState.selectedOption, questionStartTime]);

  const handleFinishQuiz = useCallback(async () => {
    if (isSubmitting) return;

    const unansweredCount = questionStates.filter(
      (s) => s.selectedOption === null
    ).length;
    if (unansweredCount > 0) {
      setError(t('selectAnswerError'));
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      const totalTimeSeconds = Math.floor((Date.now() - startTime) / 1000);

      const answers: QuizAnswerSubmission[] = quiz.content.questions.map(
        (question, index) => ({
          question_id: question.id,
          selected_option: questionStates[index].selectedOption!,
          time_taken_seconds: questionStates[index].timeSpentSeconds,
        })
      );

      const attemptResult = await submitQuizAttempt({
        quiz_id: quiz.id,
        answers,
        total_time_seconds: totalTimeSeconds,
      });

      setResult(attemptResult);
      setStage('results');

      if (attemptResult.passed) {
        setIsMarkingComplete(true);
        try {
          await completeLessonAfterQuiz({
            module_id: moduleId,
            unit_id: unitId,
            quiz_attempt_id: attemptResult.attempt_id,
          });
        } catch {
          // Non-blocking: lesson complete call failure shouldn't block success view
        } finally {
          setIsMarkingComplete(false);
        }
      }
    } catch {
      setError(t('submitError'));
    } finally {
      setIsSubmitting(false);
    }
  }, [quiz, questionStates, startTime, isSubmitting, moduleId, unitId, t]);

  const handleNextQuestion = useCallback(() => {
    if (currentQuestionIndex < totalQuestions - 1) {
      setCurrentQuestionIndex((prev) => prev + 1);
    } else {
      handleFinishQuiz();
    }
  }, [currentQuestionIndex, totalQuestions, handleFinishQuiz]);

  const handlePreviousQuestion = useCallback(() => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex((prev) => prev - 1);
    }
  }, [currentQuestionIndex]);

  const isCorrect =
    currentState.selectedOption === currentQuestion.correct_answer;

  if (stage === 'results' && result) {
    return (
      <LessonQuizResults
        quiz={quiz}
        result={result}
        isMarkingComplete={isMarkingComplete}
        onRetry={onRetry}
        onReviewLesson={onReviewLesson}
        onComplete={onComplete}
      />
    );
  }

  return (
    <div
      className="space-y-6"
      role="main"
      aria-label={t('quizAriaLabel')}
    >
      {/* Quiz Header */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-stone-900">
            {quiz.content.title}
          </h2>
          <Badge variant="outline" className="text-sm shrink-0">
            {t('questionCount', {
              current: currentQuestionIndex + 1,
              total: totalQuestions,
            })}
          </Badge>
        </div>

        <div className="space-y-1">
          <Progress value={progressPercent} className="h-2" aria-label={t('progressAriaLabel', { percent: Math.round(progressPercent) })} />
          <p className="text-xs text-stone-500 text-right">
            {Math.round(progressPercent)}%
          </p>
        </div>
      </div>

      {/* Question Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base md:text-lg leading-relaxed font-medium">
            {currentQuestion.question}
          </CardTitle>
          <div className="flex items-center gap-2 text-sm text-stone-500">
            <Badge variant="secondary" className="text-xs">
              {t('difficulty', { level: currentQuestion.difficulty })}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          <div className="space-y-3" role="radiogroup" aria-label={t('answersAriaLabel')}>
            {currentQuestion.options.map((option, index) => {
              const isSelected = currentState.selectedOption === index;
              const showResult = currentState.showFeedback;
              const isCorrectOption = index === currentQuestion.correct_answer;

              let extraClass = '';
              if (showResult) {
                if (isSelected && isCorrectOption) {
                  extraClass = 'bg-green-50 border-green-500 text-green-900';
                } else if (isSelected && !isCorrectOption) {
                  extraClass = 'bg-red-50 border-red-500 text-red-900';
                } else if (isCorrectOption) {
                  extraClass = 'bg-green-50 border-green-500 text-green-900';
                }
              }

              return (
                <button
                  key={index}
                  role="radio"
                  aria-checked={isSelected}
                  onClick={() => handleOptionSelect(index)}
                  disabled={showResult}
                  className={`w-full min-h-11 h-auto p-4 text-left border rounded-lg flex items-center gap-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 disabled:cursor-default ${
                    isSelected && !showResult
                      ? 'bg-teal-50 border-teal-500 text-teal-900'
                      : !showResult
                      ? 'border-stone-200 hover:bg-stone-50'
                      : 'border-stone-200'
                  } ${extraClass}`}
                >
                  <div className="w-6 h-6 rounded-full border-2 flex-shrink-0 flex items-center justify-center text-xs font-medium">
                    {String.fromCharCode(65 + index)}
                  </div>
                  <span className="flex-1">{option}</span>

                  {showResult && isSelected && (
                    <span className="flex-shrink-0">
                      {isCorrectOption ? (
                        <CheckCircle className="w-5 h-5 text-green-600" aria-hidden="true" />
                      ) : (
                        <XCircle className="w-5 h-5 text-red-600" aria-hidden="true" />
                      )}
                    </span>
                  )}
                  {showResult && !isSelected && isCorrectOption && (
                    <span className="flex-shrink-0">
                      <CheckCircle className="w-5 h-5 text-green-600" aria-hidden="true" />
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {/* Per-answer feedback */}
          {currentState.showFeedback && (
            <Card
              className={
                isCorrect
                  ? 'bg-green-50 border-green-200'
                  : 'bg-red-50 border-red-200'
              }
              role="status"
              aria-live="polite"
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 mt-0.5">
                    {isCorrect ? (
                      <CheckCircle className="w-5 h-5 text-green-600" aria-hidden="true" />
                    ) : (
                      <XCircle className="w-5 h-5 text-red-600" aria-hidden="true" />
                    )}
                  </div>
                  <div className="space-y-1">
                    <p
                      className={`font-medium ${
                        isCorrect ? 'text-green-900' : 'text-red-900'
                      }`}
                    >
                      {isCorrect ? t('correct') : t('incorrect')}
                    </p>
                    <p
                      className={`text-sm leading-relaxed ${
                        isCorrect ? 'text-green-800' : 'text-red-800'
                      }`}
                    >
                      {currentQuestion.explanation}
                    </p>
                    {currentQuestion.sources_cited.length > 0 && (
                      <div className="pt-2 border-t border-current opacity-60 text-xs">
                        {currentQuestion.sources_cited.map((source, idx) => (
                          <p key={idx}>{t('source', { source })}</p>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Error */}
          {error && (
            <Card className="bg-amber-50 border-amber-200" role="alert">
              <CardContent className="p-4">
                <div className="flex items-center gap-2 text-amber-700">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
                  <span className="text-sm">{error}</span>
                </div>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>

      {/* Navigation */}
      <div className="flex items-center justify-between gap-4">
        <Button
          variant="outline"
          onClick={handlePreviousQuestion}
          disabled={currentQuestionIndex === 0}
          className="min-h-11"
          aria-label={t('previousQuestion')}
        >
          <ChevronLeft className="w-4 h-4 mr-1" aria-hidden="true" />
          {t('previousQuestion')}
        </Button>

        {!currentState.showFeedback ? (
          <Button
            onClick={handleSubmitAnswer}
            disabled={currentState.selectedOption === null}
            className="min-h-11"
          >
            {t('submitAnswer')}
          </Button>
        ) : (
          <Button
            onClick={isLastQuestion ? handleFinishQuiz : handleNextQuestion}
            disabled={isSubmitting}
            className="min-h-11"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                {t('submitting')}
              </>
            ) : isLastQuestion ? (
              t('finishQuiz')
            ) : (
              <>
                {t('nextQuestion')}
                <ChevronRight className="w-4 h-4 ml-1" aria-hidden="true" />
              </>
            )}
          </Button>
        )}
      </div>

      {/* Select answer hint */}
      {!currentState.showFeedback && currentState.selectedOption === null && (
        <Card className="bg-blue-50 border-blue-200">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 text-blue-700">
              <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
              <span className="text-sm">{t('selectAnswerHint')}</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

interface LessonQuizResultsProps {
  quiz: Quiz;
  result: QuizAttemptResponse;
  isMarkingComplete: boolean;
  onRetry: () => void;
  onReviewLesson: () => void;
  onComplete: () => void;
}

function LessonQuizResults({
  quiz,
  result,
  isMarkingComplete,
  onRetry,
  onReviewLesson,
  onComplete,
}: LessonQuizResultsProps) {
  const t = useTranslations('LessonQuiz');

  const isPassed = result.passed;
  const scorePercent = result.score;
  const passingScore = quiz.content.passing_score;

  return (
    <div
      className="space-y-6"
      role="main"
      aria-label={t('resultsAriaLabel')}
    >
      {/* Result header */}
      <div className="text-center space-y-3">
        <div className="mx-auto w-16 h-16 flex items-center justify-center">
          {isPassed ? (
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
              <Trophy className="w-8 h-8 text-green-600" aria-hidden="true" />
            </div>
          ) : (
            <div className="w-16 h-16 bg-amber-100 rounded-full flex items-center justify-center">
              <Target className="w-8 h-8 text-amber-600" aria-hidden="true" />
            </div>
          )}
        </div>

        <h2 className="text-2xl font-bold text-stone-900">
          {isPassed ? t('passedTitle') : t('failedTitle')}
        </h2>
        <p className="text-stone-600">
          {isPassed ? t('passedDescription') : t('failedDescription')}
        </p>
      </div>

      {/* Score card */}
      <Card
        className={
          isPassed
            ? 'bg-green-50 border-green-200'
            : 'bg-amber-50 border-amber-200'
        }
        role="status"
        aria-label={t('scoreAriaLabel', { score: scorePercent })}
      >
        <CardContent className="p-6 text-center space-y-4">
          <div
            className={`text-5xl font-bold ${
              isPassed ? 'text-green-700' : 'text-amber-700'
            }`}
          >
            {scorePercent}%
          </div>

          <Badge
            variant={isPassed ? 'default' : 'secondary'}
            className="text-sm px-3 py-1"
          >
            {isPassed ? t('passed') : t('failed')}
          </Badge>

          <div className="space-y-2">
            <Progress
              value={scorePercent}
              className={`h-3 ${isPassed ? '[&>div]:bg-green-500' : '[&>div]:bg-amber-500'}`}
            />
            <div className="flex justify-between text-sm text-stone-600">
              <span>
                {t('correctAnswers', {
                  correct: result.correct_answers,
                  total: result.total_questions,
                })}
              </span>
              <span>{t('passingScore', { score: passingScore })}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Question breakdown */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <CheckCircle className="w-5 h-5" aria-hidden="true" />
            {t('questionBreakdown')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {result.results.map((qResult, index) => {
            const question = quiz.content.questions.find(
              (q) => q.id === qResult.question_id
            );
            if (!question) return null;

            return (
              <Card key={qResult.question_id} className="border-stone-200">
                <CardContent className="p-4 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="flex-shrink-0 mt-0.5">
                      {qResult.is_correct ? (
                        <CheckCircle className="w-4 h-4 text-green-600" aria-hidden="true" />
                      ) : (
                        <XCircle className="w-4 h-4 text-red-600" aria-hidden="true" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <Badge variant="outline" className="text-xs shrink-0">
                          Q{index + 1}
                        </Badge>
                        <span
                          className={`text-xs font-medium ${
                            qResult.is_correct
                              ? 'text-green-700'
                              : 'text-red-700'
                          }`}
                        >
                          {qResult.is_correct ? t('correct') : t('incorrect')}
                        </span>
                      </div>
                      <p className="text-sm font-medium text-stone-900 leading-relaxed">
                        {question.question}
                      </p>
                    </div>
                  </div>

                  <div className="grid md:grid-cols-2 gap-3 text-sm">
                    <div className="space-y-1">
                      <p className="font-medium text-stone-600 text-xs">
                        {t('yourAnswer')}
                      </p>
                      <div
                        className={`p-2 rounded border text-sm ${
                          qResult.is_correct
                            ? 'bg-green-50 border-green-200 text-green-800'
                            : 'bg-red-50 border-red-200 text-red-800'
                        }`}
                      >
                        {question.options[qResult.user_answer]}
                      </div>
                    </div>

                    {!qResult.is_correct && (
                      <div className="space-y-1">
                        <p className="font-medium text-stone-600 text-xs">
                          {t('correctAnswer')}
                        </p>
                        <div className="p-2 rounded border bg-green-50 border-green-200 text-green-800 text-sm">
                          {question.options[qResult.correct_answer]}
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="pt-2 border-t border-stone-100 text-sm text-stone-600">
                    <p className="font-medium text-xs text-stone-700 mb-1">
                      {t('explanation')}
                    </p>
                    <p className="leading-relaxed">{qResult.explanation}</p>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </CardContent>
      </Card>

      {/* Actions */}
      {isPassed ? (
        <div className="text-center">
          <Button
            onClick={onComplete}
            disabled={isMarkingComplete}
            size="lg"
            className="min-h-11 px-8 bg-teal-600 hover:bg-teal-700"
          >
            {isMarkingComplete ? (
              <>
                <Loader2 className="w-4 h-4 mr-2 animate-spin" aria-hidden="true" />
                {t('savingProgress')}
              </>
            ) : (
              <>
                <CheckCircle className="w-5 h-5 mr-2" aria-hidden="true" />
                {t('continueAfterPass')}
              </>
            )}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Button
            variant="outline"
            onClick={onReviewLesson}
            className="min-h-11"
          >
            <BookOpen className="w-4 h-4 mr-2" aria-hidden="true" />
            {t('reviewLesson')}
          </Button>
          <Button onClick={onRetry} className="min-h-11">
            <RotateCcw className="w-4 h-4 mr-2" aria-hidden="true" />
            {t('retryQuiz')}
          </Button>
        </div>
      )}

      <div className="sr-only" aria-live="polite">
        {t('resultsScreenReader', {
          score: scorePercent,
          correct: result.correct_answers,
          total: result.total_questions,
          passed: isPassed.toString(),
        })}
      </div>
    </div>
  );
}
