'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { cn } from '@/lib/utils';
import { useTranslations } from 'next-intl';

interface QBankQuestionTimerProps {
  totalSeconds: number;
  onExpire: () => void;
  isRunning: boolean;
  resetKey: number;
}

export function QBankQuestionTimer({ totalSeconds, onExpire, isRunning, resetKey }: QBankQuestionTimerProps) {
  const t = useTranslations('qbank');
  const [remaining, setRemaining] = useState(totalSeconds);
  const onExpireRef = useRef(onExpire);
  onExpireRef.current = onExpire;

  useEffect(() => {
    setRemaining(totalSeconds);
  }, [resetKey, totalSeconds]);

  useEffect(() => {
    if (!isRunning || remaining <= 0) return;

    const interval = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          onExpireRef.current();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [isRunning, remaining <= 0, resetKey]);

  const percentage = totalSeconds > 0 ? (remaining / totalSeconds) * 100 : 0;

  const getColor = useCallback(() => {
    if (remaining > 10) return 'bg-green-500';
    if (remaining > 5) return 'bg-yellow-500';
    return 'bg-red-500';
  }, [remaining]);

  return (
    <div className="w-full space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className={cn(
          'font-mono font-medium tabular-nums',
          remaining <= 5 && 'text-red-600 animate-pulse'
        )}>
          {t('timeRemaining', { seconds: remaining })}
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn('h-full rounded-full transition-all duration-1000 ease-linear', getColor())}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
