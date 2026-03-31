'use client';

import { useState, useRef, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function ChatInput({ onSendMessage, disabled = false, placeholder }: ChatInputProps) {
  const t = useTranslations('ChatTutor');
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const actualPlaceholder = placeholder || t('placeholder');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmedMessage = message.trim();
    if (trimmedMessage && !disabled) {
      onSendMessage(trimmedMessage);
      setMessage('');
      // Reset textarea height
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      const newHeight = Math.min(textarea.scrollHeight, 120); // Max 5 lines
      textarea.style.height = `${newHeight}px`;
    }
  }, [message]);

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2 p-4 border-t bg-background">
      <div className="flex-1 relative">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={actualPlaceholder}
          disabled={disabled}
          rows={1}
          className={cn(
            'w-full resize-none rounded-md border border-input px-3 py-2',
            'text-sm bg-background placeholder:text-muted-foreground',
            'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
            'min-h-[44px] max-h-[120px]', // Ensure minimum touch target
            disabled && 'opacity-50 cursor-not-allowed'
          )}
          style={{
            lineHeight: '1.4',
            fontSize: '16px' // Prevent iOS zoom
          }}
        />
      </div>
      <Button
        type="submit"
        size="icon"
        disabled={disabled || !message.trim()}
        className="min-h-[44px] min-w-[44px] shrink-0"
        aria-label={t('send')}
      >
        <Send className="h-4 w-4" />
      </Button>
    </form>
  );
}