'use client';

import { useState, useEffect, useRef } from 'react';
import { useTranslations } from 'next-intl';
import { X, MoreVertical, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { ChatMessage as ChatMessageComponent, type ChatMessage } from './chat-message';
import { ChatInput } from './chat-input';
import { ChatSuggestions } from './chat-suggestions';
import { TypingIndicator } from './typing-indicator';
import { UsageCounter } from './usage-counter';
import { ChatSkeleton } from './chat-skeleton';
import { cn } from '@/lib/utils';

interface ChatPanelProps {
  isOpen: boolean;
  onClose: () => void;
  moduleId?: string;
  className?: string;
}

export function ChatPanel({ isOpen, onClose, moduleId, className }: ChatPanelProps) {
  const t = useTranslations('ChatTutor');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [showClearDialog, setShowClearDialog] = useState(false);
  const [currentUsage, setCurrentUsage] = useState(0);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const maxDailyUsage = 50;
  const isLimitReached = currentUsage >= maxDailyUsage;

  // Initialize with welcome message
  useEffect(() => {
    if (messages.length === 0) {
      setMessages([
        {
          id: 'welcome',
          content: t('welcomeMessage'),
          isUser: false,
          timestamp: new Date(),
        }
      ]);
    }
  }, [t, messages.length]);

  // Scroll to bottom when new messages are added
  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollArea = scrollAreaRef.current;
      scrollArea.scrollTop = scrollArea.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSendMessage = async (messageContent: string) => {
    if (isLimitReached || isLoading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: messageContent,
      isUser: true,
      timestamp: new Date(),
    };

    setMessages(prev => [...prev, userMessage]);
    setCurrentUsage(prev => prev + 1);
    setIsLoading(true);
    setIsTyping(true);

    try {
      // Simulate API call delay
      await new Promise(resolve => setTimeout(resolve, 1500));
      
      // Mock AI response with sources
      const aiResponse: ChatMessage = {
        id: (Date.now() + 1).toString(),
        content: `Thank you for your question about "${messageContent}". This is a mock response from the AI tutor. In a real implementation, this would connect to the Claude API to generate contextual responses based on the course materials and user's current module progress.`,
        isUser: false,
        timestamp: new Date(),
        sources: [
          {
            title: 'Public Health Fundamentals',
            chapter: 3,
            page: 45
          },
          {
            title: 'Epidemiology Basics',
            chapter: 1,
            page: 12
          }
        ]
      };

      setMessages(prev => [...prev, aiResponse]);
    } catch (error) {
      console.error('Failed to send message:', error);
      // TODO: Show error message
    } finally {
      setIsLoading(false);
      setIsTyping(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (!isLimitReached && !isLoading) {
      handleSendMessage(suggestion);
    }
  };

  const handleClearHistory = () => {
    setMessages([
      {
        id: 'welcome',
        content: t('welcomeMessage'),
        isUser: false,
        timestamp: new Date(),
      }
    ]);
    setShowClearDialog(false);
  };

  if (!isOpen) return null;

  return (
    <>
      <div 
        className={cn(
          // Mobile: Full screen overlay
          'fixed inset-0 z-50 bg-background',
          // Desktop: Side panel
          'md:relative md:inset-auto md:w-96 md:border-l',
          // Animation
          'transition-transform duration-300 ease-in-out',
          isOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0',
          className
        )}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b bg-background">
          <h2 className="text-lg font-semibold">{t('title')}</h2>
          <div className="flex items-center gap-2">
            <DropdownMenu>
              <DropdownMenuTrigger>
                <Button variant="ghost" size="icon" className="h-9 w-9">
                  <MoreVertical className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setShowClearDialog(true)}>
                  <Trash2 className="h-4 w-4 mr-2" />
                  {t('clearHistory')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="h-9 w-9 md:hidden"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Usage Counter */}
        <UsageCounter 
          currentUsage={currentUsage} 
          maxUsage={maxDailyUsage}
          className="p-4 pb-2"
        />

        {/* Messages */}
        <div className="flex-1 flex flex-col min-h-0">
          <div
            ref={scrollAreaRef}
            className="flex-1 overflow-y-auto px-4 py-2"
          >
            {isLoading && messages.length <= 1 ? (
              <ChatSkeleton />
            ) : (
              <>
                {messages.map((message) => (
                  <ChatMessageComponent key={message.id} message={message} />
                ))}
                {isTyping && <TypingIndicator />}
              </>
            )}

            {/* Empty state */}
            {messages.length === 0 && !isLoading && (
              <div className="flex flex-col items-center justify-center h-full text-center p-6">
                <div className="text-muted-foreground mb-2">
                  {t('emptyState')}
                </div>
                <div className="text-sm text-muted-foreground">
                  {t('emptyStateDescription')}
                </div>
              </div>
            )}
          </div>

          {/* Suggestions */}
          {!isLimitReached && (
            <ChatSuggestions
              onSuggestionClick={handleSuggestionClick}
              disabled={isLoading}
            />
          )}

          {/* Input */}
          <ChatInput
            onSendMessage={handleSendMessage}
            disabled={isLimitReached || isLoading}
          />
        </div>
      </div>

      {/* Clear History Dialog */}
      <AlertDialog open={showClearDialog} onOpenChange={setShowClearDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('confirmClearHistory')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('confirmClearHistoryDescription')}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('cancel')}</AlertDialogCancel>
            <AlertDialogAction onClick={handleClearHistory}>
              {t('clearHistory')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}