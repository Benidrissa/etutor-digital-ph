'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Clock, ChevronLeft, ChevronRight, CheckCircle, XCircle, AlertCircle, WifiOff } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import type { Quiz, QuizAnswerSubmission, QuizAttemptResponse } from '@/lib/api';
import { submitQuizAttempt } from '@/lib/api';
import { queueOfflineAction, isOnline } from '@/lib/offline/content-loader';

interface QuizInterfaceProps {
  quiz: Quiz;
  onComplete: (result: QuizAttemptResponse) => void;
  onError: (error: string) => void;
  servedFromCache?: boolean;
}

interface QuestionState {
  selectedOption: number | null;
  timeSpentSeconds: number;
  showFeedback: boolean;
}

export function QuizInterface({ quiz, onComplete, onError, servedFromCache = false }: QuizInterfaceProps) {
  const t = useTranslations('Quiz');

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
  const [offline] = useState(!isOnline());

  const currentQuestion = quiz.content.questions[currentQuestionIndex];
  const currentState = questionStates[currentQuestionIndex];
  const totalQuestions = quiz.content.questions.length;
  const progressPercent = ((currentQuestionIndex + 1) / totalQuestions) * 100;

  // Update time spent on current question every second
  useEffect(() => {
    if (currentState.showFeedback) return;

    const interval = setInterval(() => {
      setQuestionStates(prev => prev.map((state, index) =>
        index === currentQuestionIndex
          ? { ...state, timeSpentSeconds: Math.floor((Date.now() - questionStartTime) / 1000) }
          : state
      ));
    }, 1000);

    return () => clearInterval(interval);
  }, [currentQuestionIndex, questionStartTime, currentState.showFeedback]);

  // Reset question start time when question changes
  useEffect(() => {
    setQuestionStartTime(Date.now());
  }, [currentQuestionIndex]);

  const handleOptionSelect = useCallback((optionIndex: number) => {
    if (currentState.showFeedback) return;

    setQuestionStates(prev => prev.map((state, index) =>
      index === currentQuestionIndex
        ? { ...state, selectedOption: optionIndex }
        : state
    ));
  }, [currentQuestionIndex, currentState.showFeedback]);

  const handleSubmitAnswer = useCallback(() => {
    if (currentState.selectedOption === null) return;

    const timeSpent = Math.floor((Date.now() - questionStartTime) / 1000);
    setQuestionStates(prev => prev.map((state, index) =>
      index === currentQuestionIndex
        ? { ...state, showFeedback: true, timeSpentSeconds: timeSpent }
        : state
    ));
  }, [currentQuestionIndex, currentState.selectedOption, questionStartTime]);

  const handleFinishQuiz = useCallback(async () => {
    if (isSubmitting) return;

    const unansweredQuestions = questionStates.filter(state => state.selectedOption === null);
    if (unansweredQuestions.length > 0) {
      onError(t('selectAnswer'));
      return;
    }

    setIsSubmitting(true);

    const totalTimeSeconds = Math.floor((Date.now() - startTime) / 1000);
    const answers: QuizAnswerSubmission[] = quiz.content.questions.map((question, index) => ({
      question_id: question.id,
      selected_option: questionStates[index].selectedOption!,
      time_taken_seconds: questionStates[index].timeSpentSeconds,
    }));

    // Offline: validate client-side and queue result
    if (!isOnline()) {
      const correctCount = quiz.content.questions.reduce((count, question, index) => {
        return count + (questionStates[index].selectedOption === question.correct_answer ? 1 : 0);
      }, 0);
      const score = Math.round((correctCount / totalQuestions) * 100);

      const offlineResult: QuizAttemptResponse = {
        attempt_id: `offline-${Date.now()}`,
        quiz_id: quiz.id,
        score,
        total_questions: totalQuestions,
        correct_answers: correctCount,
        total_time_seconds: totalTimeSeconds,
        passed: score >= quiz.content.passing_score,
        results: quiz.content.questions.map((question, index) => ({
          question_id: question.id,
          user_answer: questionStates[index].selectedOption!,
          correct_answer: question.correct_answer,
          is_correct: questionStates[index].selectedOption === question.correct_answer,
          explanation: question.explanation,
          time_taken_seconds: questionStates[index].timeSpentSeconds,
        })),
        attempted_at: new Date().toISOString(),
      };

      await queueOfflineAction({
        type: 'quiz_result',
        payload: {
          quiz_id: quiz.id,
          module_id: quiz.module_id,
          unit_id: quiz.unit_id,
          answers,
          total_time_seconds: totalTimeSeconds,
          score,
          correct_answers: correctCount,
          total_questions: totalQuestions,
        },
        created_at: new Date().toISOString(),
      });

      setIsSubmitting(false);
      onComplete(offlineResult);
      return;
    }

    try {
      const result = await submitQuizAttempt({
        quiz_id: quiz.id,
        answers,
        total_time_seconds: totalTimeSeconds,
      });
      onComplete(result);
    } catch {
      // Network failed mid-session — compute result client-side and queue
      const correctCount = quiz.content.questions.reduce((count, question, index) => {
        return count + (questionStates[index].selectedOption === question.correct_answer ? 1 : 0);
      }, 0);
      const score = Math.round((correctCount / totalQuestions) * 100);

      const offlineResult: QuizAttemptResponse = {
        attempt_id: `offline-${Date.now()}`,
        quiz_id: quiz.id,
        score,
        total_questions: totalQuestions,
        correct_answers: correctCount,
        total_time_seconds: totalTimeSeconds,
        passed: score >= quiz.content.passing_score,
        results: quiz.content.questions.map((question, index) => ({
          question_id: question.id,
          user_answer: questionStates[index].selectedOption!,
          correct_answer: question.correct_answer,
          is_correct: questionStates[index].selectedOption === question.correct_answer,
          explanation: question.explanation,
          time_taken_seconds: questionStates[index].timeSpentSeconds,
        })),
        attempted_at: new Date().toISOString(),
      };

      await queueOfflineAction({
        type: 'quiz_result',
        payload: {
          quiz_id: quiz.id,
          module_id: quiz.module_id,
          unit_id: quiz.unit_id,
          answers,
          total_time_seconds: totalTimeSeconds,
          score,
          correct_answers: correctCount,
          total_questions: totalQuestions,
        },
        created_at: new Date().toISOString(),
      });

      onComplete(offlineResult);
    } finally {
      setIsSubmitting(false);
    }
  }, [quiz, questionStates, startTime, totalQuestions, isSubmitting, onComplete, onError, t]);

  const handleNextQuestion = useCallback(() => {
    if (currentQuestionIndex < totalQuestions - 1) {
      setCurrentQuestionIndex(prev => prev + 1);
    } else {
      handleFinishQuiz();
    }
  }, [currentQuestionIndex, totalQuestions, handleFinishQuiz]);

  const handlePreviousQuestion = useCallback(() => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(prev => prev - 1);
    }
  }, [currentQuestionIndex]);

  const isCorrect = currentState.selectedOption === currentQuestion.correct_answer;
  const canNavigatePrevious = currentQuestionIndex > 0;
  const isLastQuestion = currentQuestionIndex === totalQuestions - 1;

  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {/* Offline banner */}
      {(offline || servedFromCache) && (
        <Card className="bg-amber-50 border-amber-200">
          <CardContent className="p-3">
            <div className="flex items-center gap-2 text-amber-700">
              <WifiOff className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{t('offlineBanner')}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Progress Header */}
      <div className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-2xl font-bold text-stone-900">
            {quiz.content.title}
          </h1>
          <Badge variant="outline" className="text-sm">
            {t('question', { current: currentQuestionIndex + 1, total: totalQuestions })}
          </Badge>
        </div>

        <div className="space-y-2">
          <div className="flex justify-between text-sm text-stone-600">
            <span>{t('question', { current: currentQuestionIndex + 1, total: totalQuestions })}</span>
            <span>{Math.round(progressPercent)}%</span>
          </div>
          <Progress value={progressPercent} className="h-2" />
        </div>
      </div>

      {/* Question Card */}
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="text-lg leading-relaxed">
            {currentQuestion.question}
          </CardTitle>

          {/* Question metadata */}
          <div className="flex items-center gap-3 text-sm text-stone-500">
            <div className="flex items-center gap-1">
              <Clock className="w-4 h-4" />
              <span>{t('timeTaken', { seconds: currentState.timeSpentSeconds })}</span>
            </div>
            <Badge variant="secondary" className="text-xs">
              {t('difficulty', { level: currentQuestion.difficulty })}
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Answer Options */}
          <div className="space-y-3">
            {currentQuestion.options.map((option, index) => {
              const isSelected = currentState.selectedOption === index;
              const showResult = currentState.showFeedback;
              const isCorrectOption = index === currentQuestion.correct_answer;

              let buttonVariant: "default" | "outline" | "secondary" = "outline";
              let className = "min-h-11 h-auto p-4 text-left justify-start";

              if (showResult) {
                if (isSelected && isCorrectOption) {
                  className += " bg-green-50 border-green-500 text-green-900";
                } else if (isSelected && !isCorrectOption) {
                  className += " bg-red-50 border-red-500 text-red-900";
                } else if (isCorrectOption) {
                  className += " bg-green-50 border-green-500 text-green-900";
                }
              } else if (isSelected) {
                buttonVariant = "default";
              }

              return (
                <Button
                  key={index}
                  variant={buttonVariant}
                  onClick={() => handleOptionSelect(index)}
                  disabled={showResult}
                  className={`w-full ${className}`}
                >
                  <div className="flex items-center gap-3 w-full">
                    <div className="w-6 h-6 rounded-full border-2 flex-shrink-0 flex items-center justify-center text-xs font-medium">
                      {String.fromCharCode(65 + index)}
                    </div>
                    <span className="flex-1 text-wrap">{option}</span>

                    {showResult && isSelected && (
                      <div className="flex-shrink-0">
                        {isCorrectOption ? (
                          <CheckCircle className="w-5 h-5 text-green-600" />
                        ) : (
                          <XCircle className="w-5 h-5 text-red-600" />
                        )}
                      </div>
                    )}

                    {showResult && !isSelected && isCorrectOption && (
                      <div className="flex-shrink-0">
                        <CheckCircle className="w-5 h-5 text-green-600" />
                      </div>
                    )}
                  </div>
                </Button>
              );
            })}
          </div>

          {/* Feedback Section */}
          {currentState.showFeedback && (
            <Card className={`${isCorrect ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'}`}>
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <div className="flex-shrink-0 mt-0.5">
                    {isCorrect ? (
                      <CheckCircle className="w-5 h-5 text-green-600" />
                    ) : (
                      <XCircle className="w-5 h-5 text-red-600" />
                    )}
                  </div>

                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <span className={`font-medium ${isCorrect ? 'text-green-900' : 'text-red-900'}`}>
                        {isCorrect ? t('correct') : t('incorrect')}
                      </span>
                    </div>

                    <div className={`text-sm ${isCorrect ? 'text-green-800' : 'text-red-800'}`}>
                      <div className="font-medium mb-1">{t('explanation')}</div>
                      <p className="leading-relaxed">{currentQuestion.explanation}</p>

                      {currentQuestion.sources_cited.length > 0 && (
                        <div className="mt-3 pt-2 border-t border-current opacity-70">
                          <div className="text-xs">
                            {currentQuestion.sources_cited.map((source, index) => (
                              <div key={index}>
                                {t('source', { source })}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </CardContent>
            </Card>
          )}
        </CardContent>
      </Card>

      {/* Navigation Controls */}
      <div className="flex items-center justify-between gap-4">
        <Button
          variant="outline"
          onClick={handlePreviousQuestion}
          disabled={!canNavigatePrevious}
          className="min-h-11"
        >
          <ChevronLeft className="w-4 h-4 mr-2" />
          {t('previousQuestion')}
        </Button>

        <div className="flex gap-2">
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
                  <AlertCircle className="w-4 h-4 mr-2 animate-spin" />
                  {t('submit')}
                </>
              ) : isLastQuestion ? (
                t('finishQuiz')
              ) : (
                <>
                  {t('nextQuestion')}
                  <ChevronRight className="w-4 h-4 ml-2" />
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Instructions */}
      {!currentState.showFeedback && currentState.selectedOption === null && (
        <Card className="bg-blue-50 border-blue-200">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-blue-700">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span className="text-sm">{t('selectAnswer')}</span>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
