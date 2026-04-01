'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { authClient } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { Clock, ChevronLeft, ChevronRight } from 'lucide-react';

interface PlacementQuestion {
  id: string;
  domain: string;
  question: string;
  options: Array<{ id: string; text: string }>;
}

interface PlacementTestData {
  questions: PlacementQuestion[];
  total_questions: number;
  time_limit_minutes: number;
  instructions: { [key: string]: string };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  domains: { [key: string]: any };
}

interface PlacementTestInterfaceProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  onComplete: (result: any) => void;
  locale: string;
}

export function PlacementTestInterface({ onComplete, locale }: PlacementTestInterfaceProps) {
  const t = useTranslations('PlacementTest');
  const [testData, setTestData] = useState<PlacementTestData | null>(null);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [answers, setAnswers] = useState<{ [key: string]: string }>({});
  const [timeLeft, setTimeLeft] = useState(20 * 60); // 20 minutes in seconds
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [startTime] = useState(Date.now());

  // Load test questions
  useEffect(() => {
    const loadQuestions = async () => {
      try {
        const data = await authClient.authenticatedFetch<PlacementTestData>(
          `/api/v1/placement-test/questions?language=${locale}`
        );
        setTestData(data);
        setTimeLeft(data.time_limit_minutes * 60);
      } catch (error) {
        console.error('Failed to load placement test questions:', error);
      } finally {
        setIsLoading(false);
      }
    };

    loadQuestions();
  }, [locale]);

  // Timer countdown
  useEffect(() => {
    if (timeLeft <= 0) {
      handleSubmit(true); // Auto-submit when time runs out
      return;
    }

    const timer = setInterval(() => {
      setTimeLeft((prev) => prev - 1);
    }, 1000);

    return () => clearInterval(timer);
  }, [timeLeft]);

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
  };

  const handleAnswerSelect = (questionId: string, answer: string) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: answer,
    }));
  };

  const handleNext = () => {
    if (currentQuestionIndex < (testData?.questions.length || 0) - 1) {
      setCurrentQuestionIndex(currentQuestionIndex + 1);
    }
  };

  const handlePrevious = () => {
    if (currentQuestionIndex > 0) {
      setCurrentQuestionIndex(currentQuestionIndex - 1);
    }
  };

  const handleSubmit = async (autoSubmit = false) => {
    if (!testData) return;

    setIsSubmitting(true);

    try {
      const timeTaken = Math.floor((Date.now() - startTime) / 1000);

      const result = await authClient.authenticatedFetch(
        '/api/v1/placement-test/submit',
        {
          method: 'POST',
          body: JSON.stringify({
            answers,
            time_taken_sec: timeTaken,
          }),
        }
      );
      onComplete(result);
    } catch (error) {
      console.error('Failed to submit placement test:', error);
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!testData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{t('title')}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-destructive">{t('error.failedToLoad')}</p>
        </CardContent>
      </Card>
    );
  }

  const currentQuestion = testData.questions[currentQuestionIndex];
  const progress = ((currentQuestionIndex + 1) / testData.total_questions) * 100;
  const answeredCount = Object.keys(answers).length;
  const canSubmit = answeredCount === testData.total_questions;

  return (
    <div className="space-y-6">
      {/* Header with timer and progress */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-xl">{t('title')}</CardTitle>
              <CardDescription>
                {t('question', {
                  current: currentQuestionIndex + 1,
                  total: testData.total_questions,
                })}
              </CardDescription>
            </div>
            <div className="flex items-center space-x-2">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <Badge variant={timeLeft < 300 ? 'destructive' : 'secondary'}>
                {t('timeRemaining', { time: formatTime(timeLeft) })}
              </Badge>
            </div>
          </div>
          <Progress value={progress} className="w-full" />
        </CardHeader>
      </Card>

      {/* Current Question */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <Badge variant="outline">
              {currentQuestion.domain.replace('_', ' ').toUpperCase()}
            </Badge>
            <span className="text-sm text-muted-foreground">
              {t('answered', { count: answeredCount, total: testData.total_questions })}
            </span>
          </div>
        </CardHeader>
        <CardContent className="space-y-6">
          <div>
            <h2 className="text-lg font-semibold mb-4">
              {currentQuestion.question}
            </h2>
            <div className="space-y-3">
              {currentQuestion.options.map((option) => (
                <button
                  key={option.id}
                  onClick={() => handleAnswerSelect(currentQuestion.id, option.id)}
                  className={`w-full p-4 text-left border rounded-lg transition-colors hover:bg-accent ${
                    answers[currentQuestion.id] === option.id
                      ? 'border-primary bg-primary/5'
                      : 'border-border'
                  }`}
                >
                  <div className="flex items-center space-x-3">
                    <div
                      className={`w-4 h-4 rounded-full border-2 ${
                        answers[currentQuestion.id] === option.id
                          ? 'border-primary bg-primary'
                          : 'border-muted-foreground'
                      }`}
                    >
                      {answers[currentQuestion.id] === option.id && (
                        <div className="w-full h-full rounded-full bg-white scale-50" />
                      )}
                    </div>
                    <span className="font-medium">{option.id.toUpperCase()}.</span>
                    <span>{option.text}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Navigation */}
      <div className="flex justify-between">
        <Button
          onClick={handlePrevious}
          variant="outline"
          disabled={currentQuestionIndex === 0}
          className="min-h-11"
        >
          <ChevronLeft className="h-4 w-4 mr-2" />
          {t('previous')}
        </Button>

        <div className="flex space-x-3">
          {currentQuestionIndex < testData.questions.length - 1 ? (
            <Button
              onClick={handleNext}
              disabled={!answers[currentQuestion.id]}
              className="min-h-11"
            >
              {t('next')}
              <ChevronRight className="h-4 w-4 ml-2" />
            </Button>
          ) : (
            <Button
              onClick={() => handleSubmit()}
              disabled={!canSubmit || isSubmitting}
              className="min-h-11 min-w-32"
            >
              {isSubmitting ? t('submitting') : t('submit')}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}