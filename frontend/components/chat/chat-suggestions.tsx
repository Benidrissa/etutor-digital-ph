'use client';

import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { MessageSquare, HelpCircle, BookOpen, Lightbulb } from 'lucide-react';

interface ChatSuggestionsProps {
  onSuggestionClick: (suggestion: string) => void;
  disabled?: boolean;
}

export function ChatSuggestions({ onSuggestionClick, disabled = false }: ChatSuggestionsProps) {
  const t = useTranslations('ChatTutor.suggestions');

  const suggestions = [
    {
      key: 'quiz',
      text: t('quiz'),
      icon: MessageSquare
    },
    {
      key: 'flashcards', 
      text: t('flashcards'),
      icon: BookOpen
    },
    {
      key: 'explain',
      text: t('explain'),
      icon: HelpCircle
    },
    {
      key: 'example',
      text: t('example'),
      icon: Lightbulb
    }
  ];

  return (
    <div className="px-4 py-2 border-t bg-muted/30">
      <div className="flex flex-wrap gap-2">
        {suggestions.map((suggestion) => {
          const Icon = suggestion.icon;
          return (
            <Button
              key={suggestion.key}
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => onSuggestionClick(suggestion.text)}
              className="min-h-[36px] text-xs"
            >
              <Icon className="h-3 w-3 mr-1" />
              {suggestion.text}
            </Button>
          );
        })}
      </div>
    </div>
  );
}