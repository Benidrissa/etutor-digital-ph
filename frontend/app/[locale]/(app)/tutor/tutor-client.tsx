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
  getCachedConversationList,
  type ConversationSummary,
} from '@/lib/tutor-api';

interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messageCount: number;
}

function summaryToConversation(s: ConversationSummary): Conversation {
  return {
    id: s.id,
    title: s.preview
      ? s.preview.slice(0, 40) + (s.preview.length > 40 ? '…' : '')
      : 'Conversation',
    lastMessage: s.preview,
    timestamp: new Date(s.last_message_at),
    messageCount: s.message_count,
  };
}

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [isLoadingList, setIsLoadingList] = useState(true);

  useEffect(() => {
    const cached = getCachedConversationList();
    if (cached && cached.conversations.length > 0) {
      const mapped = cached.conversations.map(summaryToConversation);
      setConversations(mapped);
      if (!selectedConversation && mapped.length > 0) {
        setSelectedConversation(mapped[0].id);
      }
      setIsLoadingList(false);
    }

    fetchConversations()
      .then(result => {
        const mapped = result.conversations.map(summaryToConversation);
        setConversations(mapped);
        if (!selectedConversation && mapped.length > 0) {
          setSelectedConversation(mapped[0].id);
        }
      })
      .catch(() => {
        // network error — keep cached version shown
      })
      .finally(() => {
        setIsLoadingList(false);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const formatRelativeTime = (date: Date) => {
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

  const handleConversationUpdate = (id: string, preview: string, messageCount: number) => {
    setConversations(prev => {
      const exists = prev.some(c => c.id === id);
      const updated: Conversation = {
        id,
        title: preview ? preview.slice(0, 40) + (preview.length > 40 ? '…' : '') : t('newConversationTitle'),
        lastMessage: preview,
        timestamp: new Date(),
        messageCount,
      };
      if (exists) {
        return prev.map(c => (c.id === id ? updated : c));
      }
      return [updated, ...prev];
    });
    setSelectedConversation(id);
  };

  const selectedConvData = conversations.find(c => c.id === selectedConversation);

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
                {[1, 2, 3].map(i => (
                  <div key={i} className="p-3 rounded-lg border animate-pulse">
                    <div className="h-4 w-3/4 bg-muted rounded mb-2" />
                    <div className="h-3 w-full bg-muted rounded mb-1" />
                    <div className="h-3 w-1/3 bg-muted rounded" />
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
                {conversations.map(conversation => (
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
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        setSelectedConversation(conversation.id);
                      }
                    }}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-medium text-sm truncate pr-2">{conversation.title}</h3>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatRelativeTime(conversation.timestamp)}
                      </span>
                    </div>
                    {conversation.lastMessage && (
                      <p className="text-xs text-muted-foreground truncate mb-1">
                        {conversation.lastMessage}
                      </p>
                    )}
                    <div className="flex justify-between items-center">
                      <span className="text-xs text-muted-foreground">
                        {t('messageCount', { count: conversation.messageCount })}
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
            onConversationUpdate={handleConversationUpdate}
          />
        </div>
      </div>

      {selectedConvData && (
        <div className="sr-only" aria-live="polite">
          {selectedConvData.title}
        </div>
      )}
    </ChatProvider>
  );
}
