'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Clock, ChevronLeft, ChevronRight, AlertCircle, Timer } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import type { Quiz, QuizAnswerSubmission, SummativeAssessmentResponse } from '@/lib/api';
import { submitSummativeAssessmentAttempt } from '@/lib/api';

interface SummativeAssessmentInterfaceProps {
  assessment: Quiz;
  onComplete: (result: SummativeAssessmentResponse) => void;
  onError: (error: string) => void;
  timeLimit?: number; // in minutes, default to 30
}

interface QuestionState {
  selectedOption: number | null;
  timeSpentSeconds: number;
}

const TIMER_WARNING_MINUTES = 5; // Show warning when 5 minutes left

export function SummativeAssessmentInterface({ 
  assessment, 
  onComplete, 
  onError,
  timeLimit = 30 
}: SummativeAssessmentInterfaceProps) {
  const t = useTranslations('SummativeAssessment');
  
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [questionStates, setQuestionStates] = useState<QuestionState[]>(
    assessment.content.questions.map(() => ({
      selectedOption: null,
      timeSpentSeconds: 0,
    }))
  );
  const [startTime] = useState(Date.now());
  const [questionStartTime, setQuestionStartTime] = useState(Date.now());
  const [timeRemaining, setTimeRemaining] = useState(timeLimit * 60); // Convert to seconds
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showTimeWarning, setShowTimeWarning] = useState(false);
  
  const currentQuestion = assessment.content.questions[currentQuestionIndex];
  const currentState = questionStates[currentQuestionIndex];
  const totalQuestions = assessment.content.questions.length;
  const progressPercent = ((currentQuestionIndex + 1) / totalQuestions) * 100;
  
  const handleTimeUp = useCallback(async () => {
    if (isSubmitting) return;

    const totalTimeSeconds = Math.floor((Date.now() - startTime) / 1000);

    const answers: QuizAnswerSubmission[] = assessment.content.questions.map((question, index) => ({
      question_id: question.id,
      selected_option: questionStates[index].selectedOption ?? -1,
      time_taken_seconds: questionStates[index].timeSpentSeconds,
    }));

    setIsSubmitting(true);

    try {
      const result = await submitSummativeAssessmentAttempt({
        quiz_id: assessment.id,
        answers,
        total_time_seconds: totalTimeSeconds,
      });

      onComplete(result);
    } catch (error) {
      console.error('Auto-submit failed:', error);
      onError(t('timeUpAutoSubmitFailed'));
    } finally {
      setIsSubmitting(false);
    }
  }, [assessment, questionStates, startTime, isSubmitting, onComplete, onError, t]);

  // Timer countdown effect
  useEffect(() => {
    if (timeRemaining <= 0) {
      handleTimeUp();
      return;
    }
    
    const interval = setInterval(() => {
      setTimeRemaining(prev => {
        const newTime = prev - 1;
        
        // Show warning when 5 minutes left
        if (newTime === TIMER_WARNING_MINUTES * 60 && !showTimeWarning) {
          setShowTimeWarning(true);
        }
        
        // Auto-submit when time is up
        if (newTime <= 0) {
          handleTimeUp();
          return 0;
        }
        
        return newTime;
      });
    }, 1000);
    
    return () => clearInterval(interval);
  }, [timeRemaining, showTimeWarning, handleTimeUp]);
  
  // Update time spent on current question every second
  useEffect(() => {
    const interval = setInterval(() => {
      setQuestionStates(prev => prev.map((state, index) => 
        index === currentQuestionIndex 
          ? { ...state, timeSpentSeconds: Math.floor((Date.now() - questionStartTime) / 1000) }
          : state
      ));
    }, 1000);
    
    return () => clearInterval(interval);
  }, [currentQuestionIndex, questionStartTime]);
  
  // Reset question start time when question changes
  useEffect(() => {
    setQuestionStartTime(Date.now());
  }, [currentQuestionIndex]);
  
  const handleOptionSelect = useCallback((optionIndex: number) => {
    setQuestionStates(prev => prev.map((state, index) => 
      index === currentQuestionIndex 
        ? { ...state, selectedOption: optionIndex }
        : state
    ));
  }, [currentQuestionIndex]);
  
  const handleNextQuestion = useCallback(() => {
    if (currentQuestionIndex < totalQuestions - 1) {
      setCurrentQuestionIndex(prev => prev + 1);
    }
  }, [currentQuestionIndex, totalQuestions]);
  
  const handlePreviousQuestion = useCallback(() => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(prev => prev - 1);
    }
  }, [currentQuestionIndex]);
  
  const handleFinishAssessment = useCallback(async () => {
    if (isSubmitting) return;
    
    // Check if all questions are answered
    const unansweredQuestions = questionStates.filter(state => state.selectedOption === null);
    if (unansweredQuestions.length > 0) {
      onError(t('completeAllQuestions', { count: unansweredQuestions.length }));
      return;
    }
    
    setIsSubmitting(true);
    
    try {
      const totalTimeSeconds = Math.floor((Date.now() - startTime) / 1000);
      
      const answers: QuizAnswerSubmission[] = assessment.content.questions.map((question, index) => ({
        question_id: question.id,
        selected_option: questionStates[index].selectedOption!,
        time_taken_seconds: questionStates[index].timeSpentSeconds,
      }));
      
      const result = await submitSummativeAssessmentAttempt({
        quiz_id: assessment.id,
        answers,
        total_time_seconds: totalTimeSeconds,
      });
      
      onComplete(result);
    } catch (error) {
      console.error('Assessment submission failed:', error);
      onError(t('failedToSubmit'));
    } finally {
      setIsSubmitting(false);
    }
  }, [assessment, questionStates, startTime, isSubmitting, onComplete, onError, t]);
  
  const formatTime = (seconds: number): string => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };
  
  const answeredCount = questionStates.filter(state => state.selectedOption !== null).length;
  const canNavigatePrevious = currentQuestionIndex > 0;
  const canNavigateNext = currentQuestionIndex < totalQuestions - 1;
  const isLastQuestion = currentQuestionIndex === totalQuestions - 1;
  
  return (
    <div className="max-w-4xl mx-auto p-4 space-y-6">
      {/* Time Warning Alert */}
      {showTimeWarning && timeRemaining > 0 && (
        <Alert className="bg-orange-50 border-orange-200">
          <Timer className="w-4 h-4" />
          <AlertDescription className="text-orange-800">
            {t('timeWarning', { minutes: Math.ceil(timeRemaining / 60) })}
          </AlertDescription>
        </Alert>
      )}
      
      {/* Progress Header */}
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-stone-900">
              {assessment.content.title}
            </h1>
            <p className="text-sm text-stone-600 mt-1">
              {t('instructions')}
            </p>
          </div>
          
          {/* Timer Display */}
          <div className="text-right">
            <div className={`flex items-center gap-2 text-lg font-mono ${
              timeRemaining <= TIMER_WARNING_MINUTES * 60 ? 'text-orange-600' : 'text-stone-900'
            }`}>
              <Clock className="w-5 h-5" />
              <span>{formatTime(timeRemaining)}</span>
            </div>
            <Badge variant="outline" className="text-sm mt-1">
              {t('question', { current: currentQuestionIndex + 1, total: totalQuestions })}
            </Badge>
          </div>
        </div>
        
        <div className="space-y-2">
          <div className="flex justify-between text-sm text-stone-600">
            <span>{t('progress', { answered: answeredCount, total: totalQuestions })}</span>
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
          
          <div className="text-sm text-stone-500">
            {t('selectOneAnswer')}
          </div>
        </CardHeader>
        
        <CardContent className="space-y-4">
          {/* Answer Options */}
          <div className="space-y-3">
            {currentQuestion.options.map((option, index) => {
              const isSelected = currentState.selectedOption === index;
              
              return (
                <Button
                  key={index}
                  variant={isSelected ? "default" : "outline"}
                  onClick={() => handleOptionSelect(index)}
                  className="w-full min-h-11 h-auto p-4 text-left justify-start"
                >
                  <div className="flex items-center gap-3 w-full">
                    <div className="w-6 h-6 rounded-full border-2 flex-shrink-0 flex items-center justify-center text-xs font-medium">
                      {String.fromCharCode(65 + index)}
                    </div>
                    <span className="flex-1 text-wrap">{option}</span>
                  </div>
                </Button>
              );
            })}
          </div>
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
          {t('previous')}
        </Button>
        
        <div className="flex gap-2">
          {!isLastQuestion ? (
            <Button
              onClick={handleNextQuestion}
              disabled={!canNavigateNext}
              className="min-h-11"
            >
              {t('next')}
              <ChevronRight className="w-4 h-4 ml-2" />
            </Button>
          ) : (
            <Button
              onClick={handleFinishAssessment}
              disabled={isSubmitting}
              className="min-h-11 bg-green-600 hover:bg-green-700"
            >
              {isSubmitting ? (
                <>
                  <AlertCircle className="w-4 h-4 mr-2 animate-spin" />
                  {t('submitting')}
                </>
              ) : (
                t('finishAssessment')
              )}
            </Button>
          )}
        </div>
      </div>
      
      {/* Instructions */}
      <Card className="bg-blue-50 border-blue-200">
        <CardContent className="p-4">
          <div className="flex items-start gap-2 text-blue-700 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">{t('importantNotice')}</p>
              <ul className="mt-1 space-y-1 text-xs">
                <li>• {t('noImmediateFeedback')}</li>
                <li>• {t('passingScore')}</li>
                <li>• {t('canReviewAnswers')}</li>
              </ul>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}