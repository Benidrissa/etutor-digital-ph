'use client';

import { MessageCircle } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface FloatingChatButtonProps {
  onClick: () => void;
  unreadCount?: number;
  disabled?: boolean;
  className?: string;
}

export function FloatingChatButton({ 
  onClick, 
  unreadCount = 0, 
  disabled = false, 
  className 
}: FloatingChatButtonProps) {
  const t = useTranslations('ChatTutor');

  return (
    <Button
      onClick={onClick}
      disabled={disabled}
      size="icon"
      className={cn(
        'fixed bottom-20 right-4 md:bottom-6 md:right-6',
        'h-14 w-14 rounded-full shadow-lg',
        'bg-primary hover:bg-primary/90',
        'z-50 transition-all duration-200',
        'hover:scale-105 active:scale-95',
        className
      )}
      aria-label={t('openChat')}
    >
      <div className="relative">
        <MessageCircle className="h-6 w-6" />
        {unreadCount > 0 && (
          <Badge 
            variant="destructive" 
            className="absolute -top-2 -right-2 h-5 w-5 flex items-center justify-center text-xs p-0 min-w-[20px]"
          >
            {unreadCount > 99 ? '99+' : unreadCount}
          </Badge>
        )}
      </div>
    </Button>
  );
}