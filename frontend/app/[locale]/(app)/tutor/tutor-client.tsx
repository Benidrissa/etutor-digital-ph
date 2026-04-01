'use client';

import { useState, useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Plus, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ChatPanel } from '@/components/chat';
import { ChatProvider } from '@/components/chat';
import { cn } from '@/lib/utils';
import {
  fetchConversations,
  getCachedConversations,
  setCachedConversations,
  type ConversationSummary,
} from '@/lib/tutor-api';

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);

  useEffect(() => {
    const load = async () => {
      const cached = getCachedConversations();
      if (cached.length > 0) {
        setConversations(cached);
        setSelectedConversation((prev) => (prev === null ? cached[0].id : prev));
      }

      try {
        const result = await fetchConversations(20, 0);
        setConversations(result.conversations);
        setCachedConversations(result.conversations);
        if (result.conversations.length > 0) {
          setSelectedConversation((prev) => (prev === null ? result.conversations[0].id : prev));
        }
      } catch {
        // Use cached data on network error
      } finally {
        setIsLoadingConversations(false);
      }
    };

    load();
  }, []);

  const formatRelativeTime = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

    if (diffInMinutes < 60) {
      return `${diffInMinutes}m ago`;
    } else if (diffInMinutes < 1440) {
      return `${Math.floor(diffInMinutes / 60)}h ago`;
    } else {
      return `${Math.floor(diffInMinutes / 1440)}d ago`;
    }
  };

  const handleNewConversation = () => {
    setSelectedConversation(null);
  };

  const handleConversationCreated = (newId: string) => {
    const newSummary: ConversationSummary = {
      id: newId,
      module_id: null,
      message_count: 0,
      last_message_at: new Date().toISOString(),
      preview: '',
    };
    setConversations((prev) => {
      const updated = [newSummary, ...prev];
      setCachedConversations(updated);
      return updated;
    });
    setSelectedConversation(newId);
  };

  const handleMessagesUpdated = (convId: string, preview: string, count: number) => {
    setConversations((prev) => {
      const updated = prev.map((c) =>
        c.id === convId
          ? {
              ...c,
              preview: preview + (preview.length >= 50 ? '...' : ''),
              message_count: count,
              last_message_at: new Date().toISOString(),
            }
          : c
      );
      updated.sort(
        (a, b) => new Date(b.last_message_at).getTime() - new Date(a.last_message_at).getTime()
      );
      setCachedConversations(updated);
      return updated;
    });
  };

  return (
    <ChatProvider>
      <div className="flex flex-1 min-h-0">
        <div className="w-80 border-r bg-card hidden md:flex flex-col">
          <div className="p-4 border-b">
            <Button
              className="w-full justify-start gap-2"
              variant="outline"
              onClick={handleNewConversation}
            >
              <Plus className="h-4 w-4" />
              {t('newConversation')}
            </Button>
          </div>

          <div className="flex-1 overflow-y-auto">
            {isLoadingConversations && conversations.length === 0 ? (
              <div className="p-4 text-sm text-muted-foreground text-center">{t('loading')}</div>
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
                      selectedConversation === conversation.id && 'bg-accent border-primary'
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
                          ? conversation.preview.slice(0, 30)
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

        <div className="flex-1 flex flex-col min-h-0">
          {selectedConversation !== undefined ? (
            <ChatPanel
              isOpen={true}
              onClose={() => {}}
              conversationId={selectedConversation}
              className="relative border-none w-full h-full"
              onConversationCreated={handleConversationCreated}
              onMessagesUpdated={handleMessagesUpdated}
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
              <MessageSquare className="h-16 w-16 text-muted-foreground mb-4" />
              <h2 className="text-xl font-semibold mb-2">{t('selectConversation')}</h2>
              <p className="text-muted-foreground mb-6 max-w-sm">
                {t('selectConversationDescription')}
              </p>
              <Button onClick={handleNewConversation}>
                <Plus className="h-4 w-4 mr-2" />
                {t('newConversation')}
              </Button>
            </div>
          )}
        </div>
      </div>
    </ChatProvider>
  );
}
