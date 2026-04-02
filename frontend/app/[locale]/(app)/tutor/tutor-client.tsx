'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Plus, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ChatPanel } from '@/components/chat';
import { ChatProvider } from '@/components/chat';
import { cn } from '@/lib/utils';
import {
  fetchConversations,
  invalidateConversationsCache,
  type ConversationSummary,
} from '@/lib/tutor-api';

const formatRelativeTime = (dateStr: string): string => {
  const date = new Date(dateStr);
  const now = new Date();
  const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

  if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
  if (diffInMinutes < 1440) return `${Math.floor(diffInMinutes / 60)}h ago`;
  return `${Math.floor(diffInMinutes / 1440)}d ago`;
};

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchConversations()
      .then((list) => {
        if (cancelled) return;
        setConversations(list);
        if (list.length > 0) {
          setSelectedConversation((prev) => (prev === null ? list[0].id : prev));
        }
      })
      .catch(() => {
        if (!cancelled) setConversations([]);
      })
      .finally(() => {
        if (!cancelled) setIsLoadingList(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleNewConversation = () => {
    setSelectedConversation(null);
  };

  const handleConversationSaved = useCallback(
    (newId: string) => {
      setSelectedConversation(newId);
      invalidateConversationsCache();
      fetchConversations()
        .then((list) => setConversations(list))
        .catch(() => undefined);
    },
    [],
  );

  return (
    <ChatProvider>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Conversations Sidebar - Hidden on mobile, shown on desktop */}
        <div className="w-80 border-r bg-card hidden md:flex flex-col shrink-0">
          {/* Sidebar Header */}
          <div className="p-4 border-b shrink-0">
            <Button
              className="w-full justify-start gap-2"
              variant="outline"
              onClick={handleNewConversation}
            >
              <Plus className="h-4 w-4" />
              {t('newConversation')}
            </Button>
          </div>

          {/* Conversations List */}
          <div className="flex-1 overflow-y-auto min-h-0">
            {isLoadingList ? (
              <div className="p-2 space-y-2">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="p-3 rounded-lg border animate-pulse">
                    <div className="h-4 w-3/4 mb-2 bg-muted rounded" />
                    <div className="h-3 w-full mb-1 bg-muted rounded" />
                    <div className="h-3 w-1/2 bg-muted rounded" />
                  </div>
                ))}
              </div>
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <MessageSquare className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="font-medium mb-2">{t('noConversations')}</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  {t('noConversationsDescription')}
                </p>
                <Button size="sm" onClick={handleNewConversation}>
                  <Plus className="h-4 w-4 mr-2" />
                  {t('startFirstConversation')}
                </Button>
              </div>
            ) : (
              <div className="p-2 space-y-2">
                {conversations.map((conversation) => (
                  <Card
                    key={conversation.id}
                    className={cn(
                      'p-3 cursor-pointer transition-colors hover:bg-accent/50',
                      selectedConversation === conversation.id && 'bg-accent border-primary',
                    )}
                    onClick={() => setSelectedConversation(conversation.id)}
                    role="button"
                    aria-pressed={selectedConversation === conversation.id}
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedConversation(conversation.id);
                      }
                    }}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-medium text-sm truncate pr-2">
                        {conversation.preview
                          ? conversation.preview.slice(0, 40)
                          : t('newConversationTitle')}
                      </h3>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatRelativeTime(conversation.last_message_at)}
                      </span>
                    </div>
                    {conversation.preview && (
                      <p className="text-xs text-muted-foreground truncate mb-1">
                        {conversation.preview}
                      </p>
                    )}
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">
                        {t('messageCount', { count: conversation.message_count })}
                      </span>
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          <ChatPanel
            isOpen={true}
            onClose={() => {}}
            embedded={true}
            conversationId={selectedConversation}
            onConversationSaved={handleConversationSaved}
          />
        </div>
      </div>
    </ChatProvider>
  );
}
