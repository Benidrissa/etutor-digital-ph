'use client';

import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

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

interface FlashcardSessionSummaryProps {
  stats: SessionStats;
  onContinue: () => void;
  onFinish: () => void;
  showContinueOption?: boolean;
}

export function FlashcardSessionSummary({
  stats,
  onContinue,
  onFinish,
  showContinueOption = false
}: FlashcardSessionSummaryProps) {
  const t = useTranslations('Flashcards');
  
  const minutes = Math.floor(stats.sessionDurationSeconds / 60);
  const seconds = stats.sessionDurationSeconds % 60;

  const getAccuracyColor = (accuracy: number) => {
    if (accuracy >= 80) return 'text-green-600';
    if (accuracy >= 60) return 'text-orange-600';
    return 'text-red-600';
  };

  const getRatingColor = (rating: string) => {
    switch (rating) {
      case 'again': return 'bg-red-100 text-red-800 border-red-200';
      case 'hard': return 'bg-orange-100 text-orange-800 border-orange-200';
      case 'good': return 'bg-green-100 text-green-800 border-green-200';
      case 'easy': return 'bg-blue-100 text-blue-800 border-blue-200';
      default: return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  return (
    <div className="max-w-md mx-auto px-4 py-8">
      <div className="text-center mb-6">
        <div className="text-6xl mb-4">
          {stats.accuracyPercentage >= 80 ? '🎉' : stats.accuracyPercentage >= 60 ? '👍' : '💪'}
        </div>
        <h2 className="text-2xl font-bold mb-2">{t('sessionComplete')}</h2>
        {stats.dailyTargetMet && (
          <Badge variant="secondary" className="bg-green-100 text-green-800 border-green-200">
            {t('dailyTarget')}
          </Badge>
        )}
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-lg">{t('sessionSummary')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Cards reviewed */}
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground">{t('cardsReviewed', { count: '' }).replace(': ', '')}</span>
            <span className="font-semibold">{stats.cardsReviewed}</span>
          </div>

          {/* Time spent */}
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground">{t('timeSpent', { minutes: '', seconds: '' }).replace(': m s', '')}</span>
            <span className="font-semibold">
              {t('timeSpent', { minutes, seconds })}
            </span>
          </div>

          {/* Accuracy */}
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground">{t('accuracy', { percent: '' }).replace(': %', '')}</span>
            <span className={`font-semibold ${getAccuracyColor(stats.accuracyPercentage)}`}>
              {stats.accuracyPercentage.toFixed(1)}%
            </span>
          </div>

          {/* Streak */}
          <div className="flex justify-between items-center">
            <span className="text-muted-foreground">{t('streakDays', { days: '' }).replace(': ', '').replace(' jours', '')}</span>
            <div className="flex items-center space-x-1">
              <span>🔥</span>
              <span className="font-semibold">{stats.streakDays}</span>
              <span className="text-muted-foreground text-sm">
                {stats.streakDays === 1 ? t('day') : t('days')}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Rating distribution */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-lg">{t('ratingBreakdown')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex justify-between items-center">
              <Badge variant="outline" className={getRatingColor('again')}>
                {t('again')}
              </Badge>
              <span className="font-semibold">{stats.ratingDistribution.again}</span>
            </div>
            
            <div className="flex justify-between items-center">
              <Badge variant="outline" className={getRatingColor('hard')}>
                {t('hard')}
              </Badge>
              <span className="font-semibold">{stats.ratingDistribution.hard}</span>
            </div>
            
            <div className="flex justify-between items-center">
              <Badge variant="outline" className={getRatingColor('good')}>
                {t('good')}
              </Badge>
              <span className="font-semibold">{stats.ratingDistribution.good}</span>
            </div>
            
            <div className="flex justify-between items-center">
              <Badge variant="outline" className={getRatingColor('easy')}>
                {t('easy')}
              </Badge>
              <span className="font-semibold">{stats.ratingDistribution.easy}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Encouragement message */}
      <div className="text-center mb-6">
        <p className="text-muted-foreground">
          {stats.accuracyPercentage >= 80 
            ? t('keepLearning')
            : stats.accuracyPercentage >= 60 
            ? t('goodProgress')
            : t('dontWorryProgress')
          }
        </p>
      </div>

      {/* Action buttons */}
      <div className="space-y-3">
        {showContinueOption && (
          <Button 
            variant="default" 
            className="w-full min-h-11"
            onClick={onContinue}
          >
            {t('continueSession')}
          </Button>
        )}
        
        <Button 
          variant={showContinueOption ? "outline" : "default"}
          className="w-full min-h-11"
          onClick={onFinish}
        >
          {t('finishSession')}
        </Button>
      </div>
    </div>
  );
}