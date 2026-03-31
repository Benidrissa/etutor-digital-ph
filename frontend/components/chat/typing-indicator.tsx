'use client';

import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';

interface TypingIndicatorProps {
  className?: string;
}

export function TypingIndicator({ className }: TypingIndicatorProps) {
  const t = useTranslations('ChatTutor');

  return (
    <div className={cn('flex w-full mb-4 justify-start', className)}>
      <div className="max-w-[85%] sm:max-w-[75%] rounded-lg p-3 shadow-sm bg-muted mr-4">
        <div className="flex items-center space-x-1">
          <span className="text-sm text-muted-foreground">{t('typing')}</span>
          <div className="flex space-x-1 ml-2">
            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce [animation-delay:-0.3s]" />
            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce [animation-delay:-0.15s]" />
            <div className="w-1.5 h-1.5 bg-muted-foreground rounded-full animate-bounce" />
          </div>
        </div>
      </div>
    </div>
  );
}