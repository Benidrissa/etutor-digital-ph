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
import { authClient, AuthError } from '@/lib/auth';
import { useRouter } from 'next/navigation';
import {
  fetchConversation,
  getOfflineConversation,
  invalidateConversationCache,
  invalidateConversationsCache,
} from '@/lib/tutor-api';

interface ChatPanelProps {
  isOpen: boolean;
  onClose: () => void;
  moduleId?: string;
  conversationId?: string | null;
  className?: string;
  embedded?: boolean;
  onConversationCreated?: (conversationId: string) => void;
}

export function ChatPanel({
  isOpen,
  onClose,
  moduleId,
  conversationId,
  className,
  embedded = false,
  onConversationCreated,
}: ChatPanelProps) {
  const t = useTranslations('ChatTutor');
  const router = useRouter();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isTyping, setIsTyping] = useState(false);
  const [showClearDialog, setShowClearDialog] = useState(false);
  const [currentUsage, setCurrentUsage] = useState(0);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(
    conversationId ?? null
  );
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  const maxDailyUsage = 50;
  const isLimitReached = currentUsage >= maxDailyUsage;

  const welcomeMessage: ChatMessage = {
    id: 'welcome',
    content: t('welcomeMessage'),
    isUser: false,
    timestamp: new Date(),
  };

  useEffect(() => {
    setActiveConversationId(conversationId ?? null);
  }, [conversationId]);

  useEffect(() => {
    if (!activeConversationId) {
      setMessages([welcomeMessage]);
      setCurrentUsage(0);
      return;
    }

    setIsHistoryLoading(true);
    fetchConversation(activeConversationId)
      .then((conv) => {
        const loaded: ChatMessage[] = conv.messages.map((m, i) => ({
          id: `history-${i}`,
          content: m.content,
          isUser: m.role === 'user',
          timestamp: new Date(m.timestamp),
          sources: m.sources?.map((s, j) => ({
            title: s.source ?? String(j + 1),
            chapter: s.chapter ?? j + 1,
            page: s.page ?? 0,
          })),
        }));
        const userCount = conv.messages.filter((m) => m.role === 'user').length;
        setCurrentUsage(userCount);
        setMessages(loaded.length > 0 ? loaded : [welcomeMessage]);
      })
      .catch(() => {
        const offline = getOfflineConversation(activeConversationId);
        if (offline) {
          const loaded: ChatMessage[] = offline.messages.map((m, i) => ({
            id: `offline-${i}`,
            content: m.content,
            isUser: m.role === 'user',
            timestamp: new Date(m.timestamp),
            sources: m.sources?.map((s, j) => ({
              title: s.source ?? String(j + 1),
              chapter: s.chapter ?? j + 1,
              page: s.page ?? 0,
            })),
          }));
          const userCount = offline.messages.filter((m) => m.role === 'user').length;
          setCurrentUsage(userCount);
          setMessages(loaded.length > 0 ? loaded : [welcomeMessage]);
        } else {
          setMessages([welcomeMessage]);
          setCurrentUsage(0);
        }
      })
      .finally(() => setIsHistoryLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId]);

  useEffect(() => {
    if (scrollAreaRef.current) {
      const scrollArea = scrollAreaRef.current;
      scrollArea.scrollTop = scrollArea.scrollHeight;
    }
  }, [messages, isTyping]);

  const handleSendMessage = async (messageContent: string, attachedFiles: import('./chat-input').AttachedFileInfo[] = []) => {
    if (isLimitReached || isLoading) return;

    const userMessage: ChatMessage = {
      id: Date.now().toString(),
      content: messageContent,
      isUser: true,
      timestamp: new Date(),
      attachedFiles: attachedFiles.length > 0 ? attachedFiles : undefined,
    };

    setMessages((prev) => [...prev, userMessage]);
    setCurrentUsage((prev) => prev + 1);
    setIsLoading(true);
    setIsTyping(true);

    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      let token: string;
      try {
        token = await authClient.getValidToken();
      } catch (err) {
        if (err instanceof AuthError && err.status === 401) {
          router.push('/login');
          return;
        }
        throw err;
      }
      const response = await fetch(`${API_BASE}/api/v1/tutor/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          message: messageContent,
          conversation_id: activeConversationId ?? null,
          module_id: moduleId ?? null,
          file_ids: attachedFiles.map((f) => f.fileId),
        }),
      });

      if (!response.ok) {
        if (response.status === 401) {
          router.push('/login');
          return;
        }
        throw new Error(`API error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      const aiMessageId = (Date.now() + 1).toString();

      setMessages((prev) => [
        ...prev,
        {
          id: aiMessageId,
          content: '',
          isUser: false,
          timestamp: new Date(),
        },
      ]);

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const text = decoder.decode(value, { stream: true });
          const lines = text.split('\n');

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            try {
              const chunk = JSON.parse(line.slice(6));
              if (chunk.type === 'conversation_id' && chunk.data?.conversation_id) {
                const newConvId = chunk.data.conversation_id as string;
                if (!activeConversationId) {
                  setActiveConversationId(newConvId);
                  onConversationCreated?.(newConvId);
                }
              } else if (chunk.type === 'content' && chunk.data?.text) {
                fullContent += chunk.data.text;
                setMessages((prev) =>
                  prev.map((m) => (m.id === aiMessageId ? { ...m, content: fullContent } : m))
                );
              } else if (chunk.type === 'sources_cited' && chunk.data?.sources) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId
                      ? {
                          ...m,
                          sources: chunk.data.sources.map(
                            (
                              s: { source: string; chapter?: number; page?: number },
                              i: number
                            ) => ({
                              title: s.source ?? String(i + 1),
                              chapter: s.chapter ?? i + 1,
                              page: s.page ?? 0,
                            })
                          ),
                        }
                      : m
                  )
                );
              } else if (chunk.type === 'finished' && chunk.data?.conversation_id) {
                const finishedConvId = chunk.data.conversation_id as string;
                invalidateConversationCache(finishedConvId);
                invalidateConversationsCache();
              } else if (chunk.type === 'error') {
                const errorCode = chunk.data?.code;
                fullContent =
                  errorCode === 'limit_reached' ? t('errorLimitReached') : t('error');
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === aiMessageId ? { ...m, content: fullContent } : m
                  )
                );
              }
            } catch {
              // Skip unparseable lines
            }
          }
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error);
      setMessages((prev) => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          content: t('error'),
          isUser: false,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setIsTyping(false);
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    if (!isLimitReached && !isLoading) {
      handleSendMessage(suggestion, []);
    }
  };

  const handleClearHistory = () => {
    setMessages([welcomeMessage]);
    setShowClearDialog(false);
  };

  if (!isOpen) return null;

  return (
    <>
      <div
        className={cn(
          embedded
            ? 'flex flex-col h-full w-full bg-background'
            : cn(
                'fixed inset-0 z-50 flex flex-col bg-background',
                'md:relative md:inset-auto md:w-96 md:border-l',
                'transition-transform duration-300 ease-in-out',
                isOpen ? 'translate-x-0' : 'translate-x-full md:translate-x-0'
              ),
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
          <div ref={scrollAreaRef} className="flex-1 overflow-y-auto px-4 py-2">
            {isHistoryLoading ? (
              <ChatSkeleton />
            ) : (
              <>
                {messages.map((message) => (
                  <ChatMessageComponent key={message.id} message={message} />
                ))}
                {isTyping && <TypingIndicator />}
              </>
            )}

            {messages.length === 0 && !isLoading && !isHistoryLoading && (
              <div className="flex flex-col items-center justify-center h-full text-center p-6">
                <div className="text-muted-foreground mb-2">{t('emptyState')}</div>
                <div className="text-sm text-muted-foreground">{t('emptyStateDescription')}</div>
              </div>
            )}
          </div>

          {!isLimitReached && (
            <ChatSuggestions onSuggestionClick={handleSuggestionClick} disabled={isLoading} />
          )}

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
