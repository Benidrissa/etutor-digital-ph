'use client';

import { useState, useEffect } from 'react';
import { useTranslations, useLocale } from 'next-intl';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useRouter } from '@/i18n/routing';
import { FlashcardDeck } from '@/components/learning/flashcard-deck';
import { FlashcardSessionSummary } from '@/components/learning/flashcard-session-summary';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { authClient, AuthError } from '@/lib/auth';

interface FlashcardData {
  id: string;
  card_id: string;
  card_index: number;
  term: string;
  definition_fr: string;
  definition_en: string;
  example_aof: string;
  formula?: string;
  sources_cited: string[];
  review_id: string;
  due_date: string;
  stability: number;
  difficulty: number;
}

interface FlashcardDueResponse {
  user_id: string;
  cards: FlashcardData[];
  total_due: number;
  session_target: number;
}

interface SessionStats {
  cardsReviewed: number;
  sessionDurationSeconds: number;
  accuracyPercentage: number;
  ratingDistribution: {
    again: number;
    hard: number;
    good: number;
    easy: number;
  };
  streakDays: number;
  dailyTargetMet: boolean;
}

type SessionState = 'loading' | 'ready' | 'reviewing' | 'summary' | 'empty';

export function FlashcardsContainer() {
  const t = useTranslations('Flashcards');
  const locale = useLocale();
  const router = useRouter();
  const [sessionState, setSessionState] = useState<SessionState>('loading');
  const [sessionStats, setSessionStats] = useState<SessionStats | null>(null);
  
  // Check authentication status
  const isAuthenticated = authClient.isAuthenticated();

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/login');
      return;
    }
  }, [isAuthenticated, router]);

  // Fetch due flashcards
  const { data: dueCards, isLoading, error, refetch } = useQuery({
    queryKey: ['flashcards', 'due'],
    queryFn: async () => {
      const response = await authClient.authenticatedFetch<FlashcardDueResponse>('/api/v1/flashcards/due');
      return response;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
    enabled: isAuthenticated, // Only fetch if authenticated
  });

  // Submit flashcard review
  const reviewMutation = useMutation({
    mutationFn: async ({ 
      cardId, 
      reviewId, 
      rating 
    }: { 
      cardId: string; 
      reviewId: string; 
      rating: string; 
    }) => {
      const [contentId, cardIndex] = cardId.split('_');
      
      await authClient.authenticatedFetch('/api/v1/flashcards/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          review_id: reviewId,
          card_id: contentId,
          card_index: parseInt(cardIndex),
          rating,
        }),
      });
    },
  });

  // Submit session completion
  const sessionMutation = useMutation({
    mutationFn: async (sessionData: {
      cardsReviewed: number;
      sessionDuration: number;
      ratings: string[];
    }) => {
      const response = await authClient.authenticatedFetch<{
        session_id: string;
        user_id: string;
        cards_reviewed: number;
        session_duration_seconds: number;
        accuracy_percentage: number;
        rating_distribution: {
          again: number;
          hard: number;
          good: number;
          easy: number;
        };
        streak_days: number;
        daily_target_met: boolean;
      }>('/api/v1/flashcards/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cards_reviewed: sessionData.cardsReviewed,
          session_duration_seconds: sessionData.sessionDuration,
          review_ratings: sessionData.ratings,
        }),
      });
      
      return response;
    },
    onSuccess: (data) => {
      setSessionStats({
        cardsReviewed: data.cards_reviewed,
        sessionDurationSeconds: data.session_duration_seconds,
        accuracyPercentage: data.accuracy_percentage,
        ratingDistribution: data.rating_distribution,
        streakDays: data.streak_days,
        dailyTargetMet: data.daily_target_met,
      });
      setSessionState('summary');
    },
  });

  const cardsCount = dueCards?.cards?.length ?? 0;
  const totalDue = dueCards?.total_due ?? 0;
  useEffect(() => {
    if (!isLoading) {
      if (dueCards && totalDue === 0 && cardsCount === 0) {
        setSessionState('empty');
      } else {
        setSessionState(cardsCount > 0 ? 'ready' : 'summary');
      }
    }
  }, [isLoading, cardsCount, totalDue, dueCards]);

  const handleStartSession = () => {
    setSessionState('reviewing');
  };

  const handleReview = (cardId: string, reviewId: string, rating: string) => {
    reviewMutation.mutate({ cardId, reviewId, rating });
  };

  const handleSessionComplete = (stats: {
    cardsReviewed: number;
    sessionDuration: number;
    ratings: string[];
  }) => {
    sessionMutation.mutate(stats);
  };

  const handleFinishSession = () => {
    setSessionState('ready');
    refetch(); // Refresh due cards for next session
  };

  const handleContinueSession = () => {
    refetch(); // Get more cards if available
    setSessionState('reviewing');
  };

  // Don't render anything while redirecting unauthenticated users
  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <p className="text-muted-foreground">{t('redirectingToLogin')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="max-w-md w-full mx-4">
          <CardHeader>
            <CardTitle className="text-center">{t('error')}</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <p className="text-muted-foreground">{error.message}</p>
            <Button onClick={() => refetch()}>
              {t('tryAgain')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (sessionState === 'loading' || isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-pulse mb-4">
            <div className="w-80 h-96 bg-gray-200 rounded-xl mx-auto"></div>
          </div>
          <p className="text-muted-foreground">{t('loading')}</p>
        </div>
      </div>
    );
  }

  if (sessionState === 'empty') {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="max-w-md w-full mx-4">
          <CardContent className="text-center space-y-4 py-12">
            <div className="text-6xl">📚</div>
            <h1 className="text-2xl font-bold">{t('noFlashcardsYet')}</h1>
            <p className="text-muted-foreground">{t('noFlashcardsDescription')}</p>
            <Button
              onClick={() => router.push('/modules')}
              className="w-full min-h-11"
              size="lg"
            >
              {t('goToModules')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (sessionState === 'ready') {
    if (!dueCards || dueCards.cards.length === 0) {
      return (
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center py-12">
            <div className="text-6xl mb-4">🎉</div>
            <h1 className="text-3xl font-bold mb-2">{t('noCardsToday')}</h1>
            <p className="text-muted-foreground mb-6">{t('wellDone')}</p>
            <Button onClick={() => refetch()}>
              {t('tryAgain')}
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div className="min-h-screen flex items-center justify-center">
        <Card className="max-w-md w-full mx-4">
          <CardHeader className="text-center">
            <CardTitle className="text-2xl">{t('title')}</CardTitle>
          </CardHeader>
          <CardContent className="text-center space-y-4">
            <div className="text-6xl">📚</div>
            <div className="space-y-2">
              <p className="text-lg">
                <strong>{dueCards.cards.length}</strong> {t('cardsReadyForReview')}
              </p>
              <p className="text-muted-foreground">
                {t('target')}: {dueCards.session_target} {t('cards')}
              </p>
            </div>
            <Button 
              onClick={handleStartSession}
              className="w-full min-h-11"
              size="lg"
            >
              {t('startReviewSession')}
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (sessionState === 'reviewing' && dueCards) {
    return (
      <div className="min-h-screen py-8">
        <FlashcardDeck
          cards={dueCards.cards}
          onReview={handleReview}
          onSessionComplete={handleSessionComplete}
          language={locale as 'fr' | 'en'}
        />
      </div>
    );
  }

  if (sessionState === 'summary' && sessionStats) {
    return (
      <div className="min-h-screen py-8">
        <FlashcardSessionSummary
          stats={sessionStats}
          onContinue={handleContinueSession}
          onFinish={handleFinishSession}
          showContinueOption={true}
        />
      </div>
    );
  }

  return null;
}