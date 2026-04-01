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
    title: s.preview ? s.preview.slice(0, 30) : s.id.slice(0, 8),
    lastMessage: s.preview,
    timestamp: new Date(s.last_message_at),
    messageCount: s.message_count,
  };
}

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);

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

  const loadConversations = useCallback(async () => {
    const cached = getCachedConversationList();
    if (cached && cached.conversations.length > 0) {
      setConversations(cached.conversations.map(summaryToConversation));
      setIsLoadingConversations(false);
      if (!selectedConversation) {
        setSelectedConversation(cached.conversations[0].id);
      }
    }
    try {
      const data = await fetchConversations();
      const convs = data.conversations.map(summaryToConversation);
      setConversations(convs);
      if (!selectedConversation && convs.length > 0) {
        setSelectedConversation(convs[0].id);
      }
    } catch {
      // Offline — use cached data if available
    } finally {
      setIsLoadingConversations(false);
    }
  }, [selectedConversation]);

  useEffect(() => {
    loadConversations();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleNewConversation = () => {
    const newId = `new-${Date.now()}`;
    setSelectedConversation(newId);
  };

  const handleConversationCreated = useCallback((summary: {
    id: string;
    preview: string;
    message_count: number;
    last_message_at: string;
    module_id: string | null;
  }) => {
    const newConv: Conversation = {
      id: summary.id,
      title: summary.preview ? summary.preview.slice(0, 30) : summary.id.slice(0, 8),
      lastMessage: summary.preview,
      timestamp: new Date(summary.last_message_at),
      messageCount: summary.message_count,
    };
    setConversations(prev => {
      const exists = prev.findIndex(c => c.id === summary.id);
      if (exists >= 0) {
        const updated = [...prev];
        updated[exists] = newConv;
        return updated;
      }
      return [newConv, ...prev.filter(c => !c.id.startsWith('new-'))];
    });
    setSelectedConversation(summary.id);
  }, []);

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
            {isLoadingConversations ? (
              <div className="p-4 space-y-3">
                {[1, 2, 3].map(i => (
                  <div key={i} className="h-16 bg-muted animate-pulse rounded-lg" />
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
                        {conversation.title}
                      </h3>
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
          {selectedConversation ? (
            <ChatPanel
              isOpen={true}
              onClose={() => {}}
              embedded={true}
              conversationId={selectedConversation}
              onConversationCreated={handleConversationCreated}
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

      {/* Mobile: show conversation info if needed */}
      {selectedConvData && (
        <div className="sr-only" aria-live="polite">
          {selectedConvData.title}
        </div>
      )}
    </ChatProvider>
  );
}
