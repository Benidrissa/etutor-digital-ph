'use client';

import { useEffect, useState } from 'react';
import { useTranslations } from 'next-intl';
import { useRouter } from 'next/navigation';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  getQBankTestHistory,
  type QBankTestAttemptResponse,
} from '@/lib/api';

interface QBankTestResultsProps {
  attempt: QBankTestAttemptResponse;
  testId: string;
}

export function QBankTestResults({ attempt, testId }: QBankTestResultsProps) {
  const t = useTranslations('qbank');
  const router = useRouter();
  const [history, setHistory] = useState<QBankTestAttemptResponse[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    getQBankTestHistory(testId)
      .then((h) => { if (!cancelled) setHistory(h); })
      .catch(() => { if (!cancelled) setHistory([]); });
    return () => { cancelled = true; };
  }, [testId]);

  const scorePercent = Math.round(attempt.score);
  const priorAttempts = (history ?? []).filter((a) => a.id !== attempt.id);

  return (
    <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-6 px-4 py-6">
      <div className="flex flex-col items-center gap-3">
        <div className={cn(
          'flex h-28 w-28 items-center justify-center rounded-full text-3xl font-bold',
          attempt.passed
            ? 'bg-green-100 text-green-700 dark:bg-green-950/50 dark:text-green-400'
            : 'bg-red-100 text-red-700 dark:bg-red-950/50 dark:text-red-400'
        )}>
          {scorePercent}%
        </div>
        <Badge variant={attempt.passed ? 'default' : 'destructive'}>
          {attempt.passed ? t('passed') : t('failed')}
        </Badge>
      </div>

      <Card className="w-full">
        <CardHeader>
          <CardTitle>{t('score')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{t('score')}</span>
            <span className="font-medium">{attempt.correct_answers} / {attempt.total_questions}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{t('timeTaken', { seconds: attempt.time_taken_sec })}</span>
          </div>
        </CardContent>
      </Card>

      {attempt.category_breakdown && Object.keys(attempt.category_breakdown).length > 0 && (
        <Card className="w-full">
          <CardHeader>
            <CardTitle>{t('categoryBreakdown')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {Object.entries(attempt.category_breakdown).map(([category, { correct, total }]) => {
              const pct = total > 0 ? Math.round((correct / total) * 100) : 0;
              return (
                <div key={category} className="space-y-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="truncate">{category}</span>
                    <span className="shrink-0 font-medium">{correct}/{total}</span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn(
                        'h-full rounded-full transition-all',
                        pct >= 70 ? 'bg-green-500' : pct >= 50 ? 'bg-yellow-500' : 'bg-red-500'
                      )}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {priorAttempts.length > 0 && (
        <Card className="w-full">
          <CardHeader>
            <CardTitle>{t('attemptHistory')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {priorAttempts
              .slice()
              .sort((a, b) => b.attempt_number - a.attempt_number)
              .slice(0, 5)
              .map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                >
                  <span className="text-muted-foreground">
                    #{a.attempt_number} · {new Date(a.attempted_at).toLocaleDateString()}
                  </span>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{Math.round(a.score)}%</span>
                    <Badge variant={a.passed ? 'default' : 'destructive'}>
                      {a.passed ? t('passed') : t('failed')}
                    </Badge>
                  </div>
                </div>
              ))}
          </CardContent>
        </Card>
      )}

      <div className="flex w-full gap-3">
        <Button
          variant="outline"
          className="flex-1 min-h-[44px]"
          onClick={() => router.push(`/qbank/tests/${testId}`)}
        >
          {t('retake')}
        </Button>
        <Button
          className="flex-1 min-h-[44px]"
          onClick={() => router.push(`/qbank/tests/${testId}/results?attempt_id=${attempt.id}`)}
        >
          {t('reviewAnswers')}
        </Button>
      </div>
    </div>
  );
}
