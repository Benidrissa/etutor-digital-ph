'use client';

import { useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { Link } from '@/i18n/routing';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { ClipboardList, TrendingUp, TrendingDown, Minus, Calendar, Trophy } from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface PlacementAttemptSummary {
  id: string;
  attempt_number: number;
  attempted_at: string;
  score_percentage: number;
  assigned_level: number;
  domain_scores: Record<string, number>;
  can_retake_after: string | null;
}

interface PlacementResultsHistory {
  attempts: PlacementAttemptSummary[];
  total_attempts: number;
  can_retake_now: boolean;
  next_retake_at: string | null;
}

const fetchPlacementHistory = async (): Promise<PlacementResultsHistory> => {
  const response = await fetch(`${API_BASE}/api/v1/placement-test/results`, {
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token')}`,
    },
  });
  if (!response.ok) throw new Error('Failed to fetch placement results');
  return response.json();
};

const LEVEL_COLORS: Record<number, string> = {
  1: 'bg-blue-100 text-blue-800',
  2: 'bg-green-100 text-green-800',
  3: 'bg-yellow-100 text-yellow-800',
  4: 'bg-purple-100 text-purple-800',
};

const DOMAIN_KEYS = [
  'level_1_foundations',
  'level_2_epidemiology',
  'level_3_advanced',
  'level_4_expert',
] as const;

interface PlacementResultsHistoryProps {
  showTitle?: boolean;
  compact?: boolean;
}

export function PlacementResultsHistory({
  showTitle = true,
  compact = false,
}: PlacementResultsHistoryProps) {
  const t = useTranslations('PlacementResultsHistory');

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['placement-results-history'],
    queryFn: fetchPlacementHistory,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-8">
        <LoadingSpinner />
        <span className="ml-2 text-sm text-muted-foreground">{t('loading')}</span>
      </div>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-muted-foreground">{t('error')}</p>
          <Button variant="outline" className="mt-4 min-h-11" onClick={() => refetch()}>
            {t('tryAgain')}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const history = data!;

  if (history.total_attempts === 0) {
    return (
      <Card>
        {showTitle && (
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <ClipboardList className="h-5 w-5" aria-hidden="true" />
              {t('title')}
            </CardTitle>
            <CardDescription>{t('subtitle')}</CardDescription>
          </CardHeader>
        )}
        <CardContent className="py-8 text-center">
          <p className="font-medium">{t('noResults')}</p>
          <p className="mt-1 text-sm text-muted-foreground">{t('noResultsDescription')}</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      {showTitle && (
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <ClipboardList className="h-5 w-5" aria-hidden="true" />
            {t('title')}
          </CardTitle>
          <CardDescription>{t('subtitle')}</CardDescription>
        </CardHeader>
      )}
      <CardContent className="space-y-4">
        {/* Retake eligibility banner */}
        {history.can_retake_now ? (
          <div className="rounded-md bg-green-50 p-3 text-sm text-green-800">
            {t('canRetakeNow')}
          </div>
        ) : history.next_retake_at ? (
          <div className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
            {t('canRetakeAfter', {
              date: new Intl.DateTimeFormat(undefined, {
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              }).format(new Date(history.next_retake_at)),
            })}
          </div>
        ) : null}

        {/* Attempts list */}
        <div className="space-y-4" role="list" aria-label={t('title')}>
          {history.attempts.map((attempt, index) => {
            const prevAttempt = history.attempts[index + 1];
            const scoreDelta = prevAttempt
              ? attempt.score_percentage - prevAttempt.score_percentage
              : null;

            return (
              <div
                key={attempt.id}
                role="listitem"
                className="rounded-lg border p-4 space-y-3"
              >
                {/* Attempt header */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Trophy className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    <span className="font-semibold text-sm">
                      {t('attempt', { number: attempt.attempt_number })}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Calendar className="h-3 w-3" aria-hidden="true" />
                    <time dateTime={attempt.attempted_at}>
                      {new Intl.DateTimeFormat(undefined, {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                      }).format(new Date(attempt.attempted_at))}
                    </time>
                  </div>
                </div>

                {/* Score and level */}
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-1.5">
                    <span className="text-2xl font-bold">
                      {Math.round(attempt.score_percentage)}%
                    </span>
                    {scoreDelta !== null && (
                      <span
                        className={`flex items-center gap-0.5 text-xs font-medium ${
                          scoreDelta > 0
                            ? 'text-green-600'
                            : scoreDelta < 0
                              ? 'text-red-600'
                              : 'text-muted-foreground'
                        }`}
                        aria-label={
                          scoreDelta > 0
                            ? t('scoreImprovement', { points: Math.round(scoreDelta) })
                            : scoreDelta < 0
                              ? t('scoreDecrease', { points: Math.abs(Math.round(scoreDelta)) })
                              : t('scoreSame')
                        }
                      >
                        {scoreDelta > 0 ? (
                          <TrendingUp className="h-3 w-3" aria-hidden="true" />
                        ) : scoreDelta < 0 ? (
                          <TrendingDown className="h-3 w-3" aria-hidden="true" />
                        ) : (
                          <Minus className="h-3 w-3" aria-hidden="true" />
                        )}
                        {scoreDelta > 0
                          ? `+${Math.round(scoreDelta)}`
                          : scoreDelta < 0
                            ? Math.round(scoreDelta)
                            : '—'}
                      </span>
                    )}
                  </div>
                  <Badge
                    className={`${LEVEL_COLORS[attempt.assigned_level] ?? ''} border-0 text-xs`}
                  >
                    {t('level', { level: attempt.assigned_level })}
                  </Badge>
                </div>

                {/* Domain breakdown — hidden in compact mode */}
                {!compact && Object.keys(attempt.domain_scores).length > 0 && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      {t('domainBreakdown')}
                    </p>
                    <div className="space-y-2" role="list" aria-label={t('domainBreakdown')}>
                      {DOMAIN_KEYS.map((domainKey) => {
                        const score = attempt.domain_scores[domainKey];
                        if (score === undefined) return null;
                        return (
                          <div key={domainKey} role="listitem" className="space-y-1">
                            <div className="flex items-center justify-between text-xs">
                              <span className="text-muted-foreground">
                                {t(`domains.${domainKey}`)}
                              </span>
                              <span className="font-medium">{Math.round(score)}%</span>
                            </div>
                            <Progress
                              value={score}
                              className="h-1.5"
                              aria-label={`${t(`domains.${domainKey}`)}: ${Math.round(score)}%`}
                            />
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {index < history.attempts.length - 1 && !compact && (
                  <Separator className="mt-1" />
                )}
              </div>
            );
          })}
        </div>

        {/* Retake CTA */}
        {history.can_retake_now && (
          <Link
            href="/placement-test"
            className={buttonVariants({ variant: 'default', className: 'w-full min-h-11' })}
          >
            {t('retakeTest')}
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
