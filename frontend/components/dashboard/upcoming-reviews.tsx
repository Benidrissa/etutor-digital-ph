'use client';

import { useRouter } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getUpcomingReviews, type UpcomingReviewSession } from '@/lib/api';
import { CalendarIcon, PlayIcon, AlertCircleIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

export function UpcomingReviews() {
  const t = useTranslations('Dashboard');
  const router = useRouter();
  
  const { data: upcomingReviews, isLoading, error } = useQuery({
    queryKey: ['upcoming-reviews'],
    queryFn: getUpcomingReviews,
    refetchInterval: 60000, // Refetch every minute to keep due count current
    staleTime: 30000, // Consider data fresh for 30 seconds
  });

  const handleStartReview = () => {
    router.push('/flashcards');
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    
    // Format as YYYY-MM-DD for comparison
    const dateStr = date.toISOString().split('T')[0];
    const todayStr = today.toISOString().split('T')[0];
    const tomorrowStr = tomorrow.toISOString().split('T')[0];
    
    if (dateStr === todayStr) {
      return t('today');
    } else if (dateStr === tomorrowStr) {
      return t('tomorrow');
    } else {
      return new Intl.DateTimeFormat('fr-FR', {
        weekday: 'short',
        month: 'short',
        day: 'numeric'
      }).format(date);
    }
  };

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarIcon className="w-5 h-5" />
            {t('upcomingReviews')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="animate-pulse">
                <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                  <div className="flex-1">
                    <div className="w-32 h-4 bg-muted rounded mb-2"></div>
                    <div className="w-48 h-3 bg-muted rounded"></div>
                  </div>
                  <div className="w-8 h-4 bg-muted rounded"></div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CalendarIcon className="w-5 h-5" />
            {t('upcomingReviews')}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-4 text-muted-foreground">
            <AlertCircleIcon className="w-8 h-8 mx-auto mb-2" />
            <p className="text-sm">{t('errorLoading')}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!upcomingReviews) return null;

  const { today_due_count, has_due_cards, upcoming_sessions } = upcomingReviews;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CalendarIcon className="w-5 h-5" />
            {t('upcomingReviews')}
          </div>
          {today_due_count > 0 && (
            <span className="text-sm font-normal px-2 py-1 bg-blue-100 text-blue-700 rounded-full">
              {t('dueToday', { count: today_due_count })}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {has_due_cards && (
          <div className="mb-4">
            <Button 
              onClick={handleStartReview}
              className="w-full min-h-11 bg-blue-600 hover:bg-blue-700"
              size="lg"
            >
              <PlayIcon className="w-4 h-4 mr-2" />
              {t('startReview')}
            </Button>
          </div>
        )}

        {upcoming_sessions.length === 0 ? (
          <div className="text-center py-6 text-muted-foreground">
            <CalendarIcon className="w-12 h-12 mx-auto mb-3 opacity-30" />
            <p className="text-sm">{t('noUpcomingReviews')}</p>
            <p className="text-xs mt-1">{t('keepLearning')}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {upcoming_sessions.map((session: UpcomingReviewSession, index: number) => (
              <div
                key={`${session.date}-${session.module_name}-${index}`}
                className={cn(
                  "flex items-center justify-between p-3 rounded-lg border transition-colors",
                  session.is_overdue 
                    ? "bg-red-50 border-red-200 text-red-800" 
                    : "bg-gray-50 border-gray-200"
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <p className="text-sm font-medium truncate">
                      {formatDate(session.date)}
                    </p>
                    {session.is_overdue && (
                      <AlertCircleIcon className="w-4 h-4 text-red-500 flex-shrink-0" />
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground truncate">
                    {session.module_name}
                  </p>
                </div>
                <div className="flex-shrink-0 ml-3">
                  <span className={cn(
                    "inline-flex items-center justify-center w-8 h-6 rounded-full text-xs font-medium",
                    session.is_overdue 
                      ? "bg-red-100 text-red-700" 
                      : "bg-blue-100 text-blue-700"
                  )}>
                    {session.card_count}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}