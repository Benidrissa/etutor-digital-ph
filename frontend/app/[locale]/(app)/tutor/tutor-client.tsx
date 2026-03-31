'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { Plus, MessageSquare } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ChatPanel } from '@/components/chat';
import { ChatProvider } from '@/components/chat';
import { cn } from '@/lib/utils';

interface Conversation {
  id: string;
  title: string;
  lastMessage: string;
  timestamp: Date;
  messageCount: number;
}

export function TutorPageClient() {
  const t = useTranslations('ChatTutor');
  
  // Static mock conversations data
  const conversations: Conversation[] = [
    {
      id: '1',
      title: 'Public Health Basics',
      lastMessage: 'What are the main determinants of health?',
      timestamp: new Date(2026, 2, 31, 14, 45), // 30 minutes ago (static)
      messageCount: 5,
    },
    {
      id: '2', 
      title: 'Epidemiology Questions',
      lastMessage: 'Explain the difference between incidence and prevalence',
      timestamp: new Date(2026, 2, 31, 13, 15), // 2 hours ago (static)
      messageCount: 12,
    },
    {
      id: '3',
      title: 'DHIS2 Data Analysis',
      lastMessage: 'How do I create indicators in DHIS2?',
      timestamp: new Date(2026, 2, 30, 15, 15), // 1 day ago (static)
      messageCount: 8,
    },
  ];
  
  const [selectedConversation, setSelectedConversation] = useState<string | null>('1');

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

  return (
    <ChatProvider>
      <div className="flex flex-1 min-h-0">
        {/* Conversations Sidebar - Hidden on mobile, shown on desktop */}
        <div className="w-80 border-r bg-card hidden md:flex flex-col">
          {/* Sidebar Header */}
          <div className="p-4 border-b">
            <Button 
              className="w-full justify-start gap-2" 
              variant="outline"
            >
              <Plus className="h-4 w-4" />
              {t('newConversation')}
            </Button>
          </div>

          {/* Conversations List */}
          <div className="flex-1 overflow-y-auto">
            {conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-6 text-center">
                <MessageSquare className="h-12 w-12 text-muted-foreground mb-4" />
                <h3 className="font-medium mb-2">{t('noConversations')}</h3>
                <p className="text-sm text-muted-foreground mb-4">
                  {t('noConversationsDescription')}
                </p>
                <Button size="sm">
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
                      selectedConversation === conversation.id && 'bg-accent'
                    )}
                    onClick={() => setSelectedConversation(conversation.id)}
                  >
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-medium text-sm truncate pr-2">
                        {conversation.title}
                      </h3>
                      <span className="text-xs text-muted-foreground shrink-0">
                        {formatRelativeTime(conversation.timestamp)}
                      </span>
                    </div>
                    <p className="text-xs text-muted-foreground truncate mb-1">
                      {conversation.lastMessage}
                    </p>
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
        <div className="flex-1 flex flex-col min-h-0">
          {selectedConversation ? (
            <ChatPanel 
              isOpen={true}
              onClose={() => {}} // No close action needed for full page
              className="relative border-none w-full h-full"
            />
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center p-6">
              <MessageSquare className="h-16 w-16 text-muted-foreground mb-4" />
              <h2 className="text-xl font-semibold mb-2">{t('selectConversation')}</h2>
              <p className="text-muted-foreground mb-6 max-w-sm">
                {t('selectConversationDescription')}
              </p>
              <Button>
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