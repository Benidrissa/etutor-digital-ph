'use client';

import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/routing';
import {
  Trophy,
  Target,
  Clock,
  CheckCircle,
  XCircle,
  RotateCcw,
  Eye,
  ArrowLeft,
  TrendingUp,
  History,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import type { QBankAttempt, QBankAttemptSummary } from '@/lib/api';

interface QBankTestResultsProps {
  testId: string;
  testTitle: string;
  attempt: QBankAttempt;
  passingScore: number;
  history: QBankAttemptSummary[];
}

function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  if (minutes > 0) return `${minutes}m ${remaining}s`;
  return `${seconds}s`;
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(iso));
}

export function QBankTestResults({
  testId,
  testTitle,
  attempt,
  passingScore,
  history,
}: QBankTestResultsProps) {
  const t = useTranslations('QBank');
  const router = useRouter();

  const isPassed = attempt.passed;
  const scoreColor = isPassed ? 'text-green-700' : 'text-red-700';
  const scoreBg = isPassed ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200';

  const handleRetake = () => {
    router.push(`/qbank/tests/${testId}`);
  };

  const handleReview = () => {
    router.push(`/qbank/tests/${testId}/review?attempt=${attempt.id}`);
  };

  const handleBack = () => {
    router.push('/qbank');
  };

  return (
    <div className="max-w-2xl mx-auto p-4 space-y-6">
      <div className="text-center space-y-3">
        <div
          className={`mx-auto w-20 h-20 rounded-full flex items-center justify-center ${
            isPassed ? 'bg-green-100' : 'bg-red-100'
          }`}
        >
          {isPassed ? (
            <Trophy className="w-10 h-10 text-green-600" />
          ) : (
            <Target className="w-10 h-10 text-red-600" />
          )}
        </div>
        <h1 className="text-2xl font-bold text-stone-900">{testTitle}</h1>
        <Badge
          variant={isPassed ? 'default' : 'destructive'}
          className="text-sm px-4 py-1"
        >
          {isPassed ? t('results.passed') : t('results.failed')}
        </Badge>
      </div>

      <Card className={scoreBg}>
        <CardContent className="p-6 space-y-4">
          <div className="text-center">
            <div className={`text-5xl font-bold ${scoreColor}`}>
              {attempt.score_percent}%
            </div>
            <p className="text-sm text-stone-600 mt-1">
              {t('results.passingScore', { score: passingScore })}
            </p>
          </div>

          <Progress
            value={attempt.score_percent}
            className={`h-3 ${isPassed ? '[&>div]:bg-green-500' : '[&>div]:bg-red-500'}`}
          />

          <div className="grid grid-cols-3 gap-4 pt-2 text-center">
            <div>
              <div className="flex items-center justify-center gap-1 text-green-600 mb-1">
                <CheckCircle className="w-4 h-4" />
                <span className="text-xl font-bold text-stone-900">
                  {attempt.correct_answers}
                </span>
              </div>
              <p className="text-xs text-stone-500">{t('results.correct')}</p>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1 text-red-600 mb-1">
                <XCircle className="w-4 h-4" />
                <span className="text-xl font-bold text-stone-900">
                  {attempt.total_questions - attempt.correct_answers}
                </span>
              </div>
              <p className="text-xs text-stone-500">{t('results.incorrect')}</p>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1 mb-1">
                <Clock className="w-4 h-4 text-stone-500" />
                <span className="text-xl font-bold text-stone-900">
                  {formatTime(attempt.total_time_seconds)}
                </span>
              </div>
              <p className="text-xs text-stone-500">{t('results.timeTaken')}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {attempt.category_breakdown.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="w-4 h-4" />
              {t('results.categoryBreakdown')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {attempt.category_breakdown.map((cat) => (
              <div key={cat.category} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="font-medium text-stone-700 truncate flex-1 mr-2">
                    {cat.category}
                  </span>
                  <span className="text-stone-500 shrink-0">
                    {cat.correct}/{cat.total} ({cat.score_percent}%)
                  </span>
                </div>
                <Progress
                  value={cat.score_percent}
                  className={`h-2 ${
                    cat.score_percent >= passingScore
                      ? '[&>div]:bg-green-500'
                      : '[&>div]:bg-amber-500'
                  }`}
                />
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {history.length > 1 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <History className="w-4 h-4" />
              {t('results.attemptHistory')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {history.slice(0, 5).map((h, idx) => (
                <div
                  key={h.id}
                  className="flex items-center justify-between py-2 border-b border-stone-100 last:border-0"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-stone-500">#{history.length - idx}</span>
                    <span className="text-sm text-stone-600">{formatDate(h.completed_at)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-sm font-semibold ${
                        h.passed ? 'text-green-600' : 'text-red-600'
                      }`}
                    >
                      {h.score_percent}%
                    </span>
                    <Badge variant={h.passed ? 'default' : 'secondary'} className="text-xs">
                      {h.passed ? t('results.pass') : t('results.fail')}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col sm:flex-row gap-3">
        <Button variant="outline" onClick={handleBack} className="min-h-11 sm:flex-1">
          <ArrowLeft className="w-4 h-4 mr-2" />
          {t('results.backToBank')}
        </Button>
        <Button variant="outline" onClick={handleReview} className="min-h-11 sm:flex-1">
          <Eye className="w-4 h-4 mr-2" />
          {t('results.reviewAnswers')}
        </Button>
        <Button onClick={handleRetake} className="min-h-11 sm:flex-1">
          <RotateCcw className="w-4 h-4 mr-2" />
          {t('results.retakeTest')}
        </Button>
      </div>
    </div>
  );
}
