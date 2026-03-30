'use client';

import { useTranslations } from 'next-intl';
import { Card, CardContent, CardHeader, CardDescription } from '@/components/ui/card';

interface StreakCounterProps {
  streakDays: number;
  isActiveToday: boolean;
}

export function StreakCounter({ streakDays, isActiveToday }: StreakCounterProps) {
  const t = useTranslations('Dashboard');

  return (
    <Card className="relative overflow-hidden">
      <CardHeader className="pb-2">
        <CardDescription>{t('streak')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-2">
          <span className="text-3xl font-bold">{streakDays}</span>
          <div 
            className={`text-2xl transition-all duration-300 ${
              isActiveToday && streakDays > 0 
                ? 'animate-pulse text-orange-500' 
                : 'text-gray-400'
            }`}
          >
            🔥
          </div>
        </div>
        {isActiveToday && streakDays > 0 && (
          <p className="text-sm text-green-600 mt-1 font-medium">
            {t('activeToday')}
          </p>
        )}
        {!isActiveToday && streakDays > 0 && (
          <p className="text-sm text-orange-600 mt-1">
            {t('keepStreakGoing')}
          </p>
        )}
        {streakDays === 0 && (
          <p className="text-sm text-muted-foreground mt-1">
            {t('startStreak')}
          </p>
        )}
      </CardContent>
      
      {/* Animated background glow for active streak */}
      {isActiveToday && streakDays > 0 && (
        <div className="absolute inset-0 bg-gradient-to-r from-orange-500/10 via-red-500/5 to-yellow-500/10 animate-pulse" />
      )}
    </Card>
  );
}