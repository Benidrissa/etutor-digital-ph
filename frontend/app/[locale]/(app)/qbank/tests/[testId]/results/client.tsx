'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { QBankImageQuestion } from '@/components/qbank/qbank-image-question';
import { getQBankTestReview, type QBankReviewResponse } from '@/lib/api';
import { useRouter } from 'next/navigation';

interface QBankTestResultsPageProps {
  testId: string;
  attemptId?: string;
}

export function QBankTestResultsPage({ testId, attemptId }: QBankTestResultsPageProps) {
  const t = useTranslations('qbank');
  const router = useRouter();
  const [review, setReview] = useState<QBankReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [incorrectOnly, setIncorrectOnly] = useState(false);

  useEffect(() => {
    if (!attemptId) return;
    let cancelled = false;
    getQBankTestReview(testId, attemptId)
      .then((r) => { if (!cancelled) setReview(r); })
      .catch((err) => { if (!cancelled) setError(err.message || 'Failed to load review'); });
    return () => { cancelled = true; };
  }, [testId, attemptId]);

  if (!attemptId) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center px-4">
        <p className="text-muted-foreground">Missing attempt ID</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center px-4">
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  if (!review) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 px-4">
        <LoadingSpinner className="h-8 w-8" />
        <p className="text-muted-foreground">{t('loading')}</p>
      </div>
    );
  }

  const filteredQuestions = incorrectOnly
    ? review.questions.filter((q) => q.is_correct === false)
    : review.questions;
  const totalQuestions = filteredQuestions.length;
  const safeIndex = Math.min(currentIndex, Math.max(0, totalQuestions - 1));
  const currentQuestion = filteredQuestions[safeIndex];

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge variant={review.passed ? 'default' : 'destructive'}>
          {review.passed ? t('passed') : t('failed')} — {Math.round(review.score)}%
        </Badge>
        <label className="flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={incorrectOnly}
            onChange={(e) => {
              setIncorrectOnly(e.target.checked);
              setCurrentIndex(0);
            }}
            className="h-4 w-4"
          />
          {t('showIncorrectOnly')}
        </label>
      </div>

      {totalQuestions === 0 ? (
        <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t('noIncorrect')}
        </p>
      ) : (
      <div className="space-y-2">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>{t('question', { current: safeIndex + 1, total: totalQuestions })}</span>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-primary transition-all duration-300"
            style={{ width: `${((safeIndex + 1) / totalQuestions) * 100}%` }}
          />
        </div>
      </div>
      )}

      {currentQuestion && (
        <>
          <Card className={cn(
            'border-2',
            currentQuestion.is_correct === true && 'border-green-500/50',
            currentQuestion.is_correct === false && 'border-red-500/50'
          )}>
            <CardContent className="pt-4">
              <QBankImageQuestion
                question={{
                  id: currentQuestion.id,
                  image_url: currentQuestion.image_url,
                  question_text: currentQuestion.question_text,
                  options: currentQuestion.options,
                  category: currentQuestion.category,
                  difficulty: '',
                }}
                selectedIndices={currentQuestion.user_selected ?? []}
                onToggle={() => {}}
                showFeedback={true}
                correctIndices={currentQuestion.correct_answer_indices}
              />
              {currentQuestion.explanation && (
                <div className="mt-4 rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">
                  {currentQuestion.explanation}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex items-center gap-3 pt-2">
            <Button
              variant="outline"
              className="min-h-[44px] flex-1"
              onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
              disabled={safeIndex === 0}
            >
              {t('previousQuestion')}
            </Button>
            {safeIndex < totalQuestions - 1 ? (
              <Button
                className="min-h-[44px] flex-1"
                onClick={() => setCurrentIndex((prev) => prev + 1)}
              >
                {t('nextQuestion')}
              </Button>
            ) : (
              <Button
                className="min-h-[44px] flex-1"
                onClick={() => router.push(`/qbank/tests/${testId}`)}
              >
                {t('retake')}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
