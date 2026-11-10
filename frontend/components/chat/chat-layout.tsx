'use client';

import { ChatProvider, useChatContext, ChatPanel, FloatingChatButton } from '@/components/chat';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';

function ChatUIComponents() {
  const { isOpen, closeChat, toggleChat } = useChatContext();
  const pathname = usePathname();
  
  // Extract moduleId from pathname if we're in a module page
  const moduleId = pathname.includes('/modules/') 
    ? pathname.split('/modules/')[1]?.split('/')[0]
    : undefined;

  // Hide floating button on screens where it would overlap the primary
  // action (tutor page, qbank test-taker where the sticky footer already
  // holds the Valider / Terminer button).
  const isOnTutorPage = pathname.endsWith('/tutor');
  const isOnQbankTest = /\/qbank\/tests\/[^/]+$/.test(pathname);
  const hideFab = isOnTutorPage || isOnQbankTest;
  // On a story (a module story, a story week) the button would sit on the
  // player's « Suite » at every width up to a wide desktop, where the story
  // column leaves the corner free (#2688). The tutor stays one tap away in
  // the bottom navigation and the sidebar.
  const isOnStory = /\/(story\/[^/]+|modules\/[^/]+\/story)\/?$/.test(pathname);

  return (
    <>
      {!hideFab && (
        <FloatingChatButton
          onClick={toggleChat}
          className={cn(isOpen && 'md:hidden', isOnStory && 'max-xl:hidden')}
        />
      )}
      <ChatPanel 
        isOpen={isOpen} 
        onClose={closeChat}
        moduleId={moduleId}
      />
    </>
  );
}

interface ChatLayoutProps {
  children: React.ReactNode;
}

export function ChatLayout({ children }: ChatLayoutProps) {
  return (
    <ChatProvider>
      <div className="relative">
        {children}
        <ChatUIComponents />
      </div>
    </ChatProvider>
  );
}