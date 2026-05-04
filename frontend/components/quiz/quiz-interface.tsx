'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { Clock, ChevronLeft, ChevronRight, CheckCircle, XCircle, AlertCircle } from 'lucide-react';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import type { Quiz, QuizAnswerSubmission, QuizAttemptResponse } from '@/lib/api';
import { ApiError, submitQuizAttempt } from '@/lib/api';
import { scoreQuizOffline } from '@/lib/offline/offline-quiz-scorer';
import { loadQuizState, saveQuizState, clearQuizState } from '@/lib/quiz-state-persistence';

interface QuizInterfaceProps {
  quiz: Quiz;
  onComplete: (result: QuizAttemptResponse) => void;
  onError: (error: string) => void;
}

interface QuestionState {
  selectedOption: number | null;
  timeSpentSeconds: number;
  showFeedback: boolean;
}

interface PersistedQuizState {
  currentQuestionIndex: number;
  questionStates: QuestionState[];
  startTime: number;
}

export function QuizInterface({ quiz, onComplete, onError }: QuizInterfaceProps) {
  const t = useTranslations('Quiz');

  // Quiz IDs are unique per generation, so a regenerate auto-invalidates this key.
  const storageKey = `quiz-state:v1:${quiz.id}`;
  const [restored] = useState(() => loadQuizState<PersistedQuizState>(storageKey));

  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(
    restored?.currentQuestionIndex ?? 0,
  );
  const [questionStates, setQuestionStates] = useState<QuestionState[]>(
    restored?.questionStates ??
      quiz.content.questions.map(() => ({
        selectedOption: null,
        timeSpentSeconds: 0,
        showFeedback: false,
      })),
  );
  const [startTime] = useState(restored?.startTime ?? Date.now());
  // Reconstruct questionStartTime so the per-second tick keeps adding to the
  // already-recorded time on the current question instead of resetting to 0.
  const [questionStartTime, setQuestionStartTime] = useState(() => {
    const seconds = restored?.questionStates[restored.currentQuestionIndex]?.timeSpentSeconds ?? 0;
    return Date.now() - seconds * 1000;
  });
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Persist on every meaningful state change. State is small (<10 questions),
  // so writing on every keystroke-equivalent is cheap.
  useEffect(() => {
    saveQuizState<PersistedQuizState>(storageKey, {
      currentQuestionIndex,
      questionStates,
      startTime,
    });
  }, [storageKey, currentQuestionIndex, questionStates, startTime]);
  
  const currentQuestion = quiz.content.questions[currentQuestionIndex];
  const currentState = questionStates[currentQuestionIndex];
  const totalQuestions = quiz.content.questions.length;
  const progressPercent = ((currentQuestionIndex + 1) / totalQuestions) * 100;
  
  // Update time spent on current question every second
  useEffect(() => {
    if (currentState.showFeedback) return; // Don't track time during feedback
    
    const interval = setInterval(() => {
      setQuestionStates(prev => prev.map((state, index) => 
        index === currentQuestionIndex 
          ? { ...state, timeSpentSeconds: Math.floor((Date.now() - questionStartTime) / 1000) }
          : state
      ));
    }, 1000);
    
    return () => clearInterval(interval);
  }, [currentQuestionIndex, questionStartTime, currentState.showFeedback]);
  
  // Reset question start time when question changes. Skip the first run so
  // the reconstructed questionStartTime (which preserves already-recorded
  // time on a restored attempt) isn't clobbered on mount.
  const didMountRef = useRef(false);
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
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
    
    // Check if all questions are answered
    const unansweredQuestions = questionStates.filter(state => state.selectedOption === null);
    if (unansweredQuestions.length > 0) {
      onError(t('selectAnswer'));
      return;
    }
    
    setIsSubmitting(true);

    try {
      const totalTimeSeconds = Math.floor((Date.now() - startTime) / 1000);

      const answers: QuizAnswerSubmission[] = quiz.content.questions.map((question, index) => ({
        question_id: question.id,
        selected_option: questionStates[index].selectedOption!,
        time_taken_seconds: questionStates[index].timeSpentSeconds,
      }));

      // Try server submission first; fall back to offline scoring
      if (navigator.onLine) {
        try {
          const result = await submitQuizAttempt({
            quiz_id: quiz.id,
            answers,
            total_time_seconds: totalTimeSeconds,
          });
          clearQuizState(storageKey);
          onComplete(result);
          return;
        } catch (serverErr) {
          // If it's an auth/subscription error, don't fall back
          if (serverErr instanceof ApiError && (serverErr.status === 401 || serverErr.status === 403)) {
            throw serverErr;
          }
          // Network or other error: fall back to offline scoring
          console.warn('Server quiz submit failed, scoring offline:', serverErr);
        }
      }

      // Offline scoring: compute results locally, queue for sync
      const answersMap: Record<string, number> = {};
      for (const a of answers) {
        answersMap[a.question_id] = a.selected_option;
      }
      const offlineResult = await scoreQuizOffline(quiz, answersMap, totalTimeSeconds);
      clearQuizState(storageKey);
      onComplete(offlineResult);
    } catch (error) {
      console.error('Quiz submission failed:', error);
      if (error instanceof ApiError) {
        if (error.code === 'subscription_required' || error.status === 403) {
          onError(t('subscriptionRequired'));
        } else if (error.status === 401) {
          onError(t('authRequired'));
        } else {
          onError(t('failedToSubmit'));
        }
      } else {
        onError(t('failedToSubmit'));
      }
    } finally {
      setIsSubmitting(false);
    }
  }, [quiz, questionStates, startTime, isSubmitting, onComplete, onError, t, storageKey]);

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
      {/* Progress Header */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
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
            <div className="prose prose-sm max-w-none prose-p:my-0">
              <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                {currentQuestion.question}
              </ReactMarkdown>
            </div>
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
                      <div className="leading-relaxed prose prose-sm max-w-none overflow-x-auto">
                        <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
                          {currentQuestion.explanation}
                        </ReactMarkdown>
                      </div>
                      
                      {/* Sources */}
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