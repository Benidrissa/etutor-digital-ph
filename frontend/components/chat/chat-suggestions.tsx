'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { MessageSquare, HelpCircle, BookOpen, Lightbulb, Plus } from 'lucide-react';

interface ChatSuggestionsProps {
  onSuggestionClick: (suggestion: string) => void;
  disabled?: boolean;
}

export function ChatSuggestions({ onSuggestionClick, disabled = false }: ChatSuggestionsProps) {
  const t = useTranslations('ChatTutor.suggestions');
  const [expanded, setExpanded] = useState(false);

  const suggestions = [
    {
      key: 'quiz',
      text: t('quiz'),
      icon: MessageSquare,
    },
    {
      key: 'flashcards',
      text: t('flashcards'),
      icon: BookOpen,
    },
    {
      key: 'explain',
      text: t('explain'),
      icon: HelpCircle,
    },
    {
      key: 'example',
      text: t('example'),
      icon: Lightbulb,
    },
  ];

  return (
    <div className="border-t bg-muted/30 shrink-0">
      {/* Mobile: collapsed toggle button + icon-only buttons */}
      <div className="flex items-center gap-1 px-2 py-1 md:hidden">
        <Button
          variant="ghost"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => setExpanded((v) => !v)}
          aria-label={t('toggleSuggestions')}
          aria-expanded={expanded}
        >
          <Plus
            className="h-4 w-4 transition-transform duration-200"
            style={{ transform: expanded ? 'rotate(45deg)' : 'rotate(0deg)' }}
          />
        </Button>
        {expanded &&
          suggestions.map((suggestion) => {
            const Icon = suggestion.icon;
            return (
              <Button
                key={suggestion.key}
                variant="outline"
                size="icon"
                disabled={disabled}
                onClick={() => {
                  onSuggestionClick(suggestion.text);
                  setExpanded(false);
                }}
                className="h-9 w-9 shrink-0"
                aria-label={suggestion.text}
                title={suggestion.text}
              >
                <Icon className="h-4 w-4" />
              </Button>
            );
          })}
      </div>

      {/* Desktop: full text buttons */}
      <div className="hidden md:flex flex-wrap gap-2 px-4 py-2">
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
