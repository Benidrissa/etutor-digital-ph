'use client';

import { useState, useEffect, useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Plus, MessageSquare, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ChatPanel } from '@/components/chat';
import { ChatProvider } from '@/components/chat';
import { cn } from '@/lib/utils';
import {
  fetchConversations,
  getOfflineConversations,
  invalidateConversationsCache,
  type ConversationSummary,
} from '@/lib/tutor-api';

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [selectedConversation, setSelectedConversation] = useState<string | null>(null);
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);
  const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);

  const loadConversations = useCallback(async () => {
    try {
      const data = await fetchConversations({ limit: 20 });
      setConversations(data.conversations);
      if (data.conversations.length > 0 && !selectedConversation) {
        setSelectedConversation(data.conversations[0].id);
      }
    } catch {
      const offline = getOfflineConversations();
      if (offline) {
        setConversations(offline.conversations);
        if (offline.conversations.length > 0 && !selectedConversation) {
          setSelectedConversation(offline.conversations[0].id);
        }
      }
    } finally {
      setIsLoadingConversations(false);
    }
  }, [selectedConversation]);

  useEffect(() => {
    loadConversations();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    setIsMobileDrawerOpen(false);
  };

  const handleConversationSelect = (id: string) => {
    setSelectedConversation(id);
    setIsMobileDrawerOpen(false);
  };

  const handleConversationCreated = useCallback(
    (newConversationId: string) => {
      setSelectedConversation(newConversationId);
      invalidateConversationsCache();
      fetchConversations({ limit: 20 })
        .then((data) => setConversations(data.conversations))
        .catch(() => {});
    },
    []
  );

  const selectedConvData = conversations.find((c) => c.id === selectedConversation);

  const conversationListContent = (
    <>
      <div className="p-3 border-b shrink-0">
        <Button
          className="w-full justify-start gap-2 min-h-[44px]"
          variant="outline"
          onClick={handleNewConversation}
        >
          <Plus className="h-4 w-4" />
          {t('newConversation')}
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        {isLoadingConversations ? (
          <div className="p-2 space-y-2">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="p-3 rounded-lg border animate-pulse">
                <div className="h-4 bg-muted rounded w-3/4 mb-2" />
                <div className="h-3 bg-muted rounded w-full mb-1" />
                <div className="h-3 bg-muted rounded w-1/3" />
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
            <Button size="sm" className="min-h-[44px]" onClick={handleNewConversation}>
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
                onClick={() => handleConversationSelect(conversation.id)}
                role="button"
                aria-pressed={selectedConversation === conversation.id}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleConversationSelect(conversation.id);
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
    </>
  );

  return (
    <ChatProvider>
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Conversations Sidebar — hidden on mobile, visible on desktop */}
        <div className="w-80 border-r bg-card hidden md:flex flex-col shrink-0">
          {conversationListContent}
        </div>

        {/* Mobile Drawer Backdrop */}
        {isMobileDrawerOpen && (
          <div
            className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm md:hidden"
            onClick={() => setIsMobileDrawerOpen(false)}
            aria-hidden="true"
          />
        )}

        {/* Mobile Slide-out Drawer */}
        <div
          className={cn(
            'fixed inset-y-0 left-0 z-50 w-72 bg-card border-r flex flex-col',
            'transition-transform duration-300 ease-in-out md:hidden',
            isMobileDrawerOpen ? 'translate-x-0' : '-translate-x-full'
          )}
          role="dialog"
          aria-modal="true"
          aria-label={t('conversations')}
        >
          <div className="flex items-center justify-between p-3 border-b shrink-0">
            <h2 className="font-semibold text-base">{t('conversations')}</h2>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setIsMobileDrawerOpen(false)}
              className="h-11 w-11"
              aria-label={t('closeDrawer')}
            >
              <X className="h-5 w-5" />
            </Button>
          </div>
          {conversationListContent}
        </div>

        {/* Main Chat Area */}
        <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
          {selectedConversation !== undefined ? (
            <ChatPanel
              isOpen={true}
              onClose={() => {}}
              embedded={true}
              conversationId={selectedConversation}
              onConversationCreated={handleConversationCreated}
              onOpenConversations={() => setIsMobileDrawerOpen(true)}
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
              <MessageSquare className="h-16 w-16 text-muted-foreground mb-4" />
              <h2 className="text-xl font-semibold mb-2">{t('selectConversation')}</h2>
              <p className="text-muted-foreground mb-6 max-w-sm">
                {t('selectConversationDescription')}
              </p>
              <Button className="min-h-[44px]" onClick={handleNewConversation}>
                <Plus className="h-4 w-4 mr-2" />
                {t('newConversation')}
              </Button>
            </div>
          )}
        </div>
      </div>

      {selectedConvData && (
        <div className="sr-only" aria-live="polite">
          {selectedConvData.preview || t('newConversationTitle')}
        </div>
      )}
    </ChatProvider>
  );
}
