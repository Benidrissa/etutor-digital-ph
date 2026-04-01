'use client';

import { useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { getDashboardStats } from '@/lib/api';
import { authClient } from '@/lib/auth';
import { StreakCounter } from './streak-counter';
import { StatsCard } from './stats-card';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Link } from '@/i18n/routing';

export function DashboardStats() {
  const t = useTranslations('Dashboard');
  const isAuthenticated = authClient.isAuthenticated();
  
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: getDashboardStats,
    refetchInterval: 30000, // Refetch every 30 seconds to keep streak up to date
    staleTime: 10000, // Consider data fresh for 10 seconds
    enabled: isAuthenticated, // Only fetch if user is authenticated
  });

  // Show friendly message for unauthenticated users
  if (!isAuthenticated) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-center">{t('signInToSeeProgress')}</CardTitle>
        </CardHeader>
        <CardContent className="text-center">
          <p className="text-muted-foreground mb-4">{t('signInDescription')}</p>
          <Link href="/login">
            <Button>{t('signIn')}</Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {/* Loading skeleton */}
        {[...Array(6)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardContent className="h-24 bg-muted/50" />
          </Card>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <Card className="p-4">
        <div className="text-center text-muted-foreground">
          <p>{t('errorOccurred')}</p>
          <p className="text-sm mt-1">{t('unableToLoadStats')}</p>
        </div>
      </Card>
    );
  }

  if (!stats) return null;

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {/* Streak Counter - full width on mobile, spans 2 cols on tablet+ if needed */}
      <div className="sm:col-span-2 lg:col-span-1">
        <StreakCounter 
          streakDays={stats.streak_days} 
          isActiveToday={stats.is_active_today} 
        />
      </div>

      {/* Average Quiz Score */}
      <StatsCard
        title={t('averageScore')}
        value={`${Math.round(stats.average_quiz_score)}%`}
        subtitle={stats.average_quiz_score === 0 ? 'No quizzes taken yet' : undefined}
      />

      {/* Weekly Study Time */}
      <StatsCard
        title={t('weeklyStudyTime')}
        value={stats.total_time_studied_this_week}
        subtitle={t('minutes')}
      />

      {/* Due Reviews */}
      <StatsCard
        title={t('dueReviews')}
        value={stats.next_review_count}
        subtitle={t('cards')}
      />

      {/* Modules in Progress */}
      <StatsCard
        title={t('inProgress')}
        value={stats.modules_in_progress}
        subtitle={t('modules')}
      />

      {/* Overall Progress */}
      <StatsCard
        title={t('overallProgress')}
        value={`${Math.round(stats.completion_percentage)}%`}
        subtitle={stats.completion_percentage === 0 ? 'Just getting started' : undefined}
      />
    </div>
  );
}